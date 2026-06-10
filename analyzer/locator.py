"""locator.py：从"收件根目录"或"某日期目录"中智能定位完整的 Allure 报告根。

设计目标
--------
- 用户每天把整份 allure 报告丢到 `reports_inbox/<date>/...` 即可，文件名嵌套层数随意。
- 日期目录名兼容三种写法：YYYY-MM-DD / YYYYMMDD / YYYY_MM_DD（统一归一为 YYYY-MM-DD）。
- 日期可能不在第一层（例如 `reports_inbox/projectX/2026-06-09/.../allure-report/`）。
- **支持压缩包**：日期目录里直接放 .zip / .tar / .tar.gz / .tgz / .tar.bz2 / .tbz2 也能被识别；
  收件根下顶层文件名带日期的压缩包（如 `2026-06-09.zip`）也支持。
- 报告根判定：含 `data/test-cases/` 或（`data/` + `index.html`）或 `data/test-cases/*.json`。
- 同一天目录下若发现多个 allure 报告根，**报错停下并列出所有候选**，由用户用 `--report-root` 显式指定。

仅依赖标准库（zipfile / tarfile）。
"""
import hashlib
import os
import re
import shutil
import tarfile
import zipfile


# (正则, 捕获组顺序: year, month, day)
_DATE_PATTERNS = [
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), "dash"),
    (re.compile(r"^(\d{4})_(\d{2})_(\d{2})$"), "underscore"),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"),   "compact"),
]

# 支持的压缩包后缀（按长后缀优先匹配）
_ARCHIVE_EXTS = (
    ".tar.gz", ".tar.bz2", ".tgz", ".tbz2",
    ".zip", ".tar",
)


class LocatorError(Exception):
    """定位失败：让上层根据 message 决定退出码和提示。"""


# ---------------------------------------------------------------------------
# 日期解析
# ---------------------------------------------------------------------------

def normalize_date(name):
    """把字符串解析为归一化日期 'YYYY-MM-DD'，无法解析返回 None。

    会自动去掉常见压缩包后缀，因此 `2026-06-09.zip` 也能解析为 `2026-06-09`。
    """
    n = name
    low = n.lower()
    for ext in _ARCHIVE_EXTS:
        if low.endswith(ext):
            n = n[: -len(ext)]
            break
    for pat, _ in _DATE_PATTERNS:
        m = pat.match(n)
        if m:
            y, mo, d = m.group(1), m.group(2), m.group(3)
            try:
                yi, mi, di = int(y), int(mo), int(d)
                if not (1 <= mi <= 12 and 1 <= di <= 31 and 1970 <= yi <= 9999):
                    return None
            except ValueError:
                return None
            return "%s-%s-%s" % (y, mo, d)
    return None


# ---------------------------------------------------------------------------
# 压缩包支持
# ---------------------------------------------------------------------------

def is_archive(path):
    """判定是否为支持的压缩包文件。"""
    if not os.path.isfile(path):
        return False
    low = path.lower()
    return any(low.endswith(ext) for ext in _ARCHIVE_EXTS)


def _archive_stem(filename):
    """去掉压缩包后缀，返回基础名（用于做缓存子目录名）。"""
    low = filename.lower()
    for ext in _ARCHIVE_EXTS:
        if low.endswith(ext):
            return filename[: -len(ext)]
    return filename


def _archive_fingerprint(path):
    """给压缩包生成一个稳定指纹（size+mtime），用于缓存幂等。"""
    st = os.stat(path)
    raw = "%s|%d|%d" % (os.path.abspath(path), st.st_size, int(st.st_mtime))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _safe_extract_zip(zf, dest):
    """zip 解压：跳过路径穿越的成员（防 zip-slip）。"""
    dest_abs = os.path.abspath(dest)
    members = []
    for info in zf.infolist():
        # 处理可能的 cp437 乱码：先尝试用 utf-8 重新解码
        name = info.filename
        try:
            # zipfile 默认按 cp437 解码非 UTF-8 标记的文件名
            if not (info.flag_bits & 0x800):
                raw = name.encode("cp437", errors="replace")
                # 优先 utf-8，其次 gbk（Windows 中文常见）
                for enc in ("utf-8", "gbk"):
                    try:
                        name = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
        except Exception:
            pass
        target = os.path.normpath(os.path.join(dest_abs, name))
        if not target.startswith(dest_abs + os.sep) and target != dest_abs:
            continue  # zip-slip 防御
        if info.is_dir() or name.endswith("/"):
            os.makedirs(target, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(info, "r") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        members.append(target)
    return members


def _safe_extract_tar(tf, dest):
    """tar 解压：跳过路径穿越/绝对路径/链接外指的成员。"""
    dest_abs = os.path.abspath(dest)
    safe_members = []
    for m in tf.getmembers():
        if m.name.startswith("/") or ".." in m.name.split("/"):
            continue
        target = os.path.normpath(os.path.join(dest_abs, m.name))
        if not (target == dest_abs or target.startswith(dest_abs + os.sep)):
            continue
        if m.issym() or m.islnk():
            # 直接跳过链接成员
            continue
        safe_members.append(m)
    tf.extractall(dest, members=safe_members)
    return safe_members


def extract_archive(archive_path, dest_dir, force=False, log=None):
    """把压缩包解压到 dest_dir。完成后写一个 .ok 标记，便于幂等。

    Args:
        archive_path: 源压缩包绝对路径。
        dest_dir: 目标目录（建议形如 <cache_root>/<date>/<stem>__<fp>/）。
        force: 即便 .ok 标记存在也强制重解。
        log: 可选回调 fn(msg)。

    Returns:
        dest_dir（解压后目录），失败抛 LocatorError。
    """
    def _say(msg):
        if log:
            log(msg)

    fp = _archive_fingerprint(archive_path)
    ok_flag = os.path.join(dest_dir, ".unpack.ok")
    if (not force) and os.path.isfile(ok_flag):
        with open(ok_flag, "r", encoding="utf-8") as f:
            if f.read().strip() == fp:
                _say("[unpack] cache hit: %s" % archive_path)
                return dest_dir
        # 指纹变了，重解
        shutil.rmtree(dest_dir, ignore_errors=True)
    if os.path.isdir(dest_dir):
        # 残留目录但无 ok：清空重解
        shutil.rmtree(dest_dir, ignore_errors=True)
    os.makedirs(dest_dir, exist_ok=True)

    low = archive_path.lower()
    try:
        if low.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                _safe_extract_zip(zf, dest_dir)
        else:
            # tar 系列：tarfile 自动识别 gz/bz2
            with tarfile.open(archive_path, "r:*") as tf:
                _safe_extract_tar(tf, dest_dir)
    except Exception as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise LocatorError("解压失败 %s：%s" % (archive_path, e))

    with open(ok_flag, "w", encoding="utf-8") as f:
        f.write(fp)
    _say("[unpack] %s -> %s" % (archive_path, dest_dir))
    return dest_dir


def find_archives_in_dir(date_dir, max_depth=2):
    """浅扫日期目录下的压缩包（默认 2 层内，避免深入解压结果）。

    返回：[abs_path, ...]，按字典序。
    """
    found = []
    date_dir = os.path.abspath(date_dir)
    if not os.path.isdir(date_dir):
        return found

    def _walk(cur, depth):
        if depth > max_depth:
            return
        try:
            entries = sorted(os.listdir(cur))
        except OSError:
            return
        for name in entries:
            if name.startswith("."):
                continue
            p = os.path.join(cur, name)
            if os.path.isfile(p) and is_archive(p):
                found.append(p)
            elif os.path.isdir(p) and not os.path.islink(p):
                _walk(p, depth + 1)

    _walk(date_dir, 0)
    return found


def _cache_target_for_archive(cache_root, date_str, archive_path):
    """给压缩包计算缓存解压目录：<cache_root>/<date>/<stem>__<fp>/"""
    stem = _archive_stem(os.path.basename(archive_path))
    fp = _archive_fingerprint(archive_path)
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem) or "archive"
    return os.path.join(cache_root, date_str, "%s__%s" % (safe_stem, fp))


def prepare_search_roots(date_dir, date_str, cache_root, auto_unpack=True, log=None):
    """为定位 allure 报告根准备所有"搜索起点"。

    步骤：
      1) date_dir 自身就是一个搜索起点（已经解压好的目录形态）。
      2) 若 auto_unpack=True，扫 date_dir 下的压缩包，逐个解压到
         `<cache_root>/<date>/<stem>__<fp>/`，把这些解压目标也加入搜索起点。

    返回：list of (search_root_abs, kind)，kind ∈ {"dir", "unpacked:<archive>"}。
    """
    roots = [(os.path.abspath(date_dir), "dir")]
    if not auto_unpack:
        return roots
    archives = find_archives_in_dir(date_dir)
    for arch in archives:
        target = _cache_target_for_archive(cache_root, date_str, arch)
        try:
            extract_archive(arch, target, log=log)
            roots.append((target, "unpacked:%s" % os.path.basename(arch)))
        except LocatorError as e:
            if log:
                log("[unpack][WARN] %s" % e)
            # 跳过这个压缩包，继续处理其他来源
    return roots


# ---------------------------------------------------------------------------
# allure 报告根识别
# ---------------------------------------------------------------------------

def is_allure_report_root(path):
    """判定一个目录是否为完整的 allure 报告根。"""
    if not os.path.isdir(path):
        return False
    data_dir = os.path.join(path, "data")
    tc_dir = os.path.join(data_dir, "test-cases")
    has_index = os.path.isfile(os.path.join(path, "index.html"))
    if os.path.isdir(tc_dir):
        try:
            for n in os.listdir(tc_dir):
                if n.endswith(".json"):
                    return True
        except OSError:
            return False
    if has_index and os.path.isdir(data_dir):
        return True
    return False


def find_report_roots(start_dir, max_depth=6):
    """从 start_dir 起向下递归寻找所有 allure 报告根。

    返回：[(absolute_path, depth_from_start), ...]，按 (depth, path) 升序。
    一旦命中某目录是报告根，就不再深入其子目录（避免把 history/ 之类误判）。
    """
    found = []
    start_dir = os.path.abspath(start_dir)
    if not os.path.isdir(start_dir):
        return found

    def _walk(cur, depth):
        if depth > max_depth:
            return
        if is_allure_report_root(cur):
            found.append((cur, depth))
            return
        try:
            entries = sorted(os.listdir(cur))
        except OSError:
            return
        for name in entries:
            if name.startswith("."):
                continue
            sub = os.path.join(cur, name)
            if os.path.isdir(sub) and not os.path.islink(sub):
                _walk(sub, depth + 1)

    _walk(start_dir, 0)
    found.sort(key=lambda x: (x[1], x[0]))
    return found


def find_all_report_roots(date_dir, date_str, cache_root, auto_unpack=True, log=None):
    """汇总该日期下所有 allure 报告根候选（合并目录形态 + 解压形态）。

    返回：[(report_root_abs, depth, source), ...]，source 标识来自哪条搜索根。
    """
    all_found = []
    seen = set()
    for search_root, kind in prepare_search_roots(date_dir, date_str, cache_root,
                                                  auto_unpack=auto_unpack, log=log):
        for p, depth in find_report_roots(search_root):
            if p in seen:
                continue
            seen.add(p)
            all_found.append((p, depth, kind))
    # 按 (depth, path) 排序
    all_found.sort(key=lambda x: (x[1], x[0]))
    return all_found


# ---------------------------------------------------------------------------
# 收件根扫描
# ---------------------------------------------------------------------------

def find_date_dirs(inbox_root, max_depth=4):
    """在 inbox_root 下扫描所有名字符合日期格式的目录（任意层级）。

    返回：[(date_str, abs_path, depth), ...]，按 (date_str, depth, path) 排序。
    """
    results = []
    inbox_root = os.path.abspath(inbox_root)
    if not os.path.isdir(inbox_root):
        return results

    def _walk(cur, depth):
        if depth > max_depth:
            return
        try:
            entries = sorted(os.listdir(cur))
        except OSError:
            return
        for name in entries:
            if name.startswith("."):
                continue
            sub = os.path.join(cur, name)
            if not os.path.isdir(sub) or os.path.islink(sub):
                continue
            d = normalize_date(name)
            if d is not None:
                results.append((d, sub, depth))
                continue  # 日期目录内部不再继续找日期目录
            _walk(sub, depth + 1)

    _walk(inbox_root, 0)
    results.sort(key=lambda x: (x[0], x[2], x[1]))
    return results


def find_date_archives(inbox_root, max_depth=2):
    """在 inbox_root 下扫描"文件名带日期"的压缩包（如 `2026-06-09.zip`）。

    只在浅层扫，避免深入到日期目录内部把里面的压缩包也算成顶层归档。
    返回：[(date_str, abs_path, depth), ...]
    """
    results = []
    inbox_root = os.path.abspath(inbox_root)
    if not os.path.isdir(inbox_root):
        return results

    def _walk(cur, depth):
        if depth > max_depth:
            return
        try:
            entries = sorted(os.listdir(cur))
        except OSError:
            return
        for name in entries:
            if name.startswith("."):
                continue
            sub = os.path.join(cur, name)
            if os.path.isfile(sub) and is_archive(sub):
                d = normalize_date(name)
                if d is not None:
                    results.append((d, sub, depth))
            elif os.path.isdir(sub) and not os.path.islink(sub):
                # 日期目录不进去（它会被 find_date_dirs 处理）
                if normalize_date(name) is None:
                    _walk(sub, depth + 1)

    _walk(inbox_root, 0)
    results.sort(key=lambda x: (x[0], x[2], x[1]))
    return results


# ---------------------------------------------------------------------------
# 公开入口
# ---------------------------------------------------------------------------

def locate_report_for_date(date_dir, cache_root, allow_pick=False,
                           auto_unpack=True, log=None):
    """在指定的"日期目录"下找出唯一的 allure 报告根（自动解压压缩包）。

    Args:
        date_dir: 日期目录绝对路径。
        cache_root: 解压缓存根目录（如 `<allure_analyzer>/trend_data/_unpack_cache`）。
        allow_pick: True 时多候选不抛异常，返回 (None, candidates)。
        auto_unpack: 是否自动解压日期目录下的压缩包，默认 True。
        log: 可选 fn(msg)。

    Returns:
        (report_root_abspath, candidates_list)

    Raises:
        LocatorError
    """
    date_str = normalize_date(os.path.basename(date_dir)) or ""
    candidates = find_all_report_roots(date_dir, date_str, cache_root,
                                       auto_unpack=auto_unpack, log=log)
    if not candidates:
        raise LocatorError(
            "在日期目录下未找到完整的 Allure 报告（需含 data/test-cases/*.json）：%s" % date_dir
        )
    if len(candidates) == 1:
        return candidates[0][0], [candidates[0][0]]
    paths = [p for p, _, _ in candidates]
    if allow_pick:
        return None, paths
    lines = ["在日期目录下发现多个 Allure 报告候选，请用 --report-root 显式指定其中之一："]
    lines.append("  日期目录: %s" % date_dir)
    for p, depth, source in candidates:
        try:
            rel = os.path.relpath(p, date_dir)
        except ValueError:
            rel = p
        lines.append("  [depth=%d, from=%s] %s" % (depth, source, rel))
    raise LocatorError("\n".join(lines))


def _ensure_unpacked_for_date_archive(archive_path, date_str, cache_root, log=None):
    """把"文件名带日期"的顶层压缩包解压到缓存，返回解压后目录。"""
    target = _cache_target_for_archive(cache_root, date_str, archive_path)
    extract_archive(archive_path, target, log=log)
    return target


def resolve_targets(inbox_or_date_dir, cache_root, auto_unpack=True, log=None):
    """统一入口：识别传入的目录是"收件根"还是"日期目录"，并解析出所有日期 → 报告根。

    Args:
        inbox_or_date_dir: 收件根 或 单个日期目录。
        cache_root: 解压缓存根目录。
        auto_unpack: 默认 True；False 时不解压压缩包，仅按目录形态处理。
        log: 可选 fn(msg)。

    Returns:
        list of dict: [{
            "date": "YYYY-MM-DD",
            "date_dir": abs,            # 可能是真目录，也可能是从顶层 zip 解压出来的目录
            "report_root": abs or None,
            "candidates": [...] (仅多候选时),
            "error": str (仅出错时),
            "source": "dir" | "archive:<path>",
        }]
    """
    inbox_or_date_dir = os.path.abspath(inbox_or_date_dir)
    base = os.path.basename(inbox_or_date_dir)
    self_date = normalize_date(base)

    # 单文件场景：直接传入一个日期压缩包
    if os.path.isfile(inbox_or_date_dir) and is_archive(inbox_or_date_dir):
        if not self_date:
            return [{
                "date": "",
                "date_dir": inbox_or_date_dir,
                "report_root": None,
                "error": "压缩包文件名未包含可识别的日期：%s" % base,
                "source": "archive:%s" % inbox_or_date_dir,
            }]
        try:
            ddir = _ensure_unpacked_for_date_archive(
                inbox_or_date_dir, self_date, cache_root, log=log)
        except LocatorError as e:
            return [{"date": self_date, "date_dir": inbox_or_date_dir,
                     "report_root": None, "error": str(e),
                     "source": "archive:%s" % inbox_or_date_dir}]
        item = {"date": self_date, "date_dir": ddir, "report_root": None,
                "source": "archive:%s" % inbox_or_date_dir}
        try:
            root, _ = locate_report_for_date(
                ddir, cache_root, allow_pick=False,
                auto_unpack=auto_unpack, log=log)
            item["report_root"] = root
        except LocatorError as e:
            cands = find_all_report_roots(ddir, self_date, cache_root,
                                          auto_unpack=auto_unpack, log=log)
            if len(cands) > 1:
                item["candidates"] = [p for p, _, _ in cands]
            item["error"] = str(e)
        return [item]

    targets = []

    if self_date is not None:
        # 传入本身就是一个日期目录
        date_entries = [(self_date, inbox_or_date_dir, "dir")]
    else:
        # 收件根：日期目录 + 顶层日期压缩包
        date_entries = []
        for d, p, _depth in find_date_dirs(inbox_or_date_dir):
            date_entries.append((d, p, "dir"))
        if auto_unpack:
            for d, p, _depth in find_date_archives(inbox_or_date_dir):
                # 与同名日期目录共存时也照样列出，由后续的多候选机制阻塞
                date_entries.append((d, p, "archive"))
        date_entries.sort(key=lambda x: (x[0], x[1]))

    # 把"日期级压缩包"展开为"虚拟日期目录"
    norm_entries = []  # list of (date_str, date_dir_abs, source_str)
    for date_str, path, kind in date_entries:
        if kind == "archive":
            try:
                ddir = _ensure_unpacked_for_date_archive(
                    path, date_str, cache_root, log=log)
            except LocatorError as e:
                targets.append({"date": date_str, "date_dir": path,
                                "report_root": None, "error": str(e),
                                "source": "archive:%s" % path})
                continue
            norm_entries.append((date_str, ddir, "archive:%s" % path))
        else:
            norm_entries.append((date_str, path, "dir"))

    # 同一天可能有多条（目录 + 顶层 zip）：合并候选后再判定
    by_date = {}
    for date_str, ddir, src in norm_entries:
        by_date.setdefault(date_str, []).append((ddir, src))

    for date_str in sorted(by_date.keys()):
        entries = by_date[date_str]
        # 收集所有候选 allure 报告根
        all_roots = []  # (path, depth, source)
        seen = set()
        for ddir, src in entries:
            for p, depth, kind in find_all_report_roots(
                    ddir, date_str, cache_root,
                    auto_unpack=auto_unpack, log=log):
                if p in seen:
                    continue
                seen.add(p)
                # 把外层 source（archive: 或 dir）和内层（unpacked: 或 dir）拼起来
                merged_src = src if kind == "dir" else "%s|%s" % (src, kind)
                all_roots.append((p, depth, merged_src))
        # 主"日期目录"：第一条 dir entry 优先；没有则取第一条
        primary = next((d for d, s in entries if s == "dir"), entries[0][0])
        primary_src = next((s for d, s in entries if s == "dir"),
                           entries[0][1])
        item = {"date": date_str, "date_dir": primary, "report_root": None,
                "source": primary_src}
        if not all_roots:
            item["error"] = "在日期 %s 下未找到完整的 Allure 报告。" % date_str
        elif len(all_roots) == 1:
            item["report_root"] = all_roots[0][0]
        else:
            item["candidates"] = [p for p, _, _ in all_roots]
            lines = ["日期 %s 下发现多个 Allure 报告候选：" % date_str]
            for p, depth, src in all_roots:
                lines.append("  [depth=%d, from=%s] %s" % (depth, src, p))
            item["error"] = "\n".join(lines)
        targets.append(item)

    return targets

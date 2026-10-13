# -*- coding: utf-8 -*-
"""Baffox 文件夹同步 FolderSync — 简单的手动文件夹同步工具 (Windows / tkinter)。

https://baffox.com  ·  MIT License
"""
import os
import sys
import json
import shutil
import threading
from datetime import datetime

APP_NAME = "Baffox 文件夹同步 FolderSync"
APP_VERSION = "1.1.0"
TRASH_DIR_NAME = ".foldersync_trash"
SETTINGS_NAME = "sync_settings.json"
LOG_NAME = "sync_errors.log"


# ---------------------------------------------------------------- paths
def _is_writable_dir(path):
    try:
        test = os.path.join(path, ".foldersync_write_test")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
        return True
    except OSError:
        return False


def get_app_dir():
    """设置/日志目录：exe 或脚本所在目录；不可写时用 %APPDATA%\\BaffoxFolderSync。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    if _is_writable_dir(base):
        return base
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(appdata, "BaffoxFolderSync")
    os.makedirs(path, exist_ok=True)
    return path


def load_pairs(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []
    return []


def save_pairs(path, pairs):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pairs, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- core logic
def _norm(p):
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def is_inside(child, parent):
    """child 是否等于 parent 或位于 parent 之内。"""
    c, p = _norm(child), _norm(parent)
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:  # 不同盘符
        return False


def validate_pair(source, target):
    """返回错误信息字符串；合法时返回 None。"""
    if not source or not target:
        return "请选择源目录和目标目录"
    if _norm(source) == _norm(target):
        return "源目录和目标目录不能相同"
    if is_inside(target, source):
        return "目标目录不能放在源目录里面（会无限复制）"
    if is_inside(source, target):
        return "源目录不能放在目标目录里面（完全同步时可能删掉源文件）"
    return None


def plan_sync(source, target, mode):
    """生成同步计划，不改动任何文件。

    返回 dict: copies=[(src, dst, rel)], deletions=[rel(文件或目录)], skipped=int, errors=[str]
    """
    plan = {"source": source, "target": target, "mode": mode,
            "copies": [], "deletions": [], "skipped": 0, "errors": []}
    err = validate_pair(source, target)
    if err:
        plan["errors"].append(f"{err}: {source} -> {target}")
        return plan
    if not os.path.isdir(source):
        plan["errors"].append(f"源目录不存在: {source}")
        return plan

    for root, dirs, files in os.walk(source):
        dirs[:] = [d for d in dirs if d != TRASH_DIR_NAME]
        rel_root = os.path.relpath(root, source)
        for name in files:
            rel = name if rel_root == "." else os.path.join(rel_root, name)
            src = os.path.join(root, name)
            dst = os.path.join(target, rel)
            if os.path.exists(dst):
                if mode != "full":
                    plan["skipped"] += 1
                    continue
                try:
                    same = (os.path.getsize(src) == os.path.getsize(dst) and
                            int(os.path.getmtime(src)) == int(os.path.getmtime(dst)))
                except OSError:
                    same = False
                if same:
                    plan["skipped"] += 1
                    continue
            plan["copies"].append((src, dst, rel))

    if mode == "full" and os.path.isdir(target):
        for root, dirs, files in os.walk(target):
            rel_root = os.path.relpath(root, target)
            src_root = source if rel_root == "." else os.path.join(source, rel_root)
            keep = []
            for d in dirs:
                if rel_root == "." and d == TRASH_DIR_NAME:
                    continue
                rel = d if rel_root == "." else os.path.join(rel_root, d)
                if os.path.isdir(os.path.join(src_root, d)):
                    keep.append(d)
                else:
                    plan["deletions"].append(rel + os.sep)  # 整个目录
            dirs[:] = keep
            for name in files:
                if not os.path.isfile(os.path.join(src_root, name)):
                    plan["deletions"].append(name if rel_root == "." else os.path.join(rel_root, name))
    return plan


def move_to_trash(path, target_root, use_send2trash=True, stamp=None):
    """删除到回收站；失败时移动到 target_root/.foldersync_trash/<时间>/。绝不永久删除。

    返回 "recycle" 或 "fallback"。"""
    if use_send2trash:
        try:
            from send2trash import send2trash
            send2trash(os.path.abspath(path))
            return "recycle"
        except Exception:
            pass
    stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    rel = os.path.relpath(path, target_root)
    dest = os.path.join(target_root, TRASH_DIR_NAME, stamp, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(path, dest)
    return "fallback"


def execute_plan(plan, do_delete=True, use_send2trash=True, progress=None):
    """执行计划。返回 dict(copied, deleted, skipped, errors, trash_fallback)。"""
    res = {"copied": 0, "deleted": 0, "skipped": plan["skipped"],
           "errors": list(plan["errors"]), "trash_fallback": 0}
    if plan["errors"] and not plan["copies"] and not plan["deletions"]:
        return res
    target = plan["target"]
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as e:
        res["errors"].append(f"无法创建目标目录: {target}: {e}")
        return res
    for src, dst, rel in plan["copies"]:
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            res["copied"] += 1
            if progress:
                progress(f"正在复制: {rel}")
        except Exception as e:
            res["errors"].append(f"复制失败: {src} -> {dst}: {e}")
    if do_delete and plan["mode"] == "full":
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for rel in plan["deletions"]:
            path = os.path.join(target, rel.rstrip("\\/"))
            if not os.path.lexists(path):
                continue
            try:
                how = move_to_trash(path, target, use_send2trash, stamp)
                res["deleted"] += 1
                if how == "fallback":
                    res["trash_fallback"] += 1
                if progress:
                    progress(f"已移到回收站: {rel}")
            except Exception as e:
                res["errors"].append(f"删除失败: {path}: {e}")
    return res


def write_error_log(log_path, errors):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
        for e in errors:
            f.write(e + "\n")
        f.write("\n")


# ---------------------------------------------------------------- GUI
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    FONT = "微软雅黑"
    BRAND = "#e8590c"

    class SyncToolApp:
        def __init__(self, root):
            self.root = root
            self.root.title(f"{APP_NAME} v{APP_VERSION}")
            self.root.geometry("850x620")
            self.app_dir = get_app_dir()
            self.settings_path = os.path.join(self.app_dir, SETTINGS_NAME)
            self.log_path = os.path.join(self.app_dir, LOG_NAME)
            self.sync_pairs = load_pairs(self.settings_path)
            self.last_errors = []
            self.running = False
            self.setup_ui()

        def save_settings(self):
            try:
                save_pairs(self.settings_path, self.sync_pairs)
            except OSError as e:
                messagebox.showerror("保存失败", f"无法保存设置：{e}")

        def setup_ui(self):
            tk.Label(self.root, text=APP_NAME, font=(FONT, 16, "bold"), fg=BRAND).pack(pady=10)
            tk.Label(self.root, text="手动触发同步 · 设置自动保存", font=(FONT, 9), fg="#888").pack()
            mf = tk.Frame(self.root)
            mf.pack(pady=5)
            tk.Label(mf, text="完全同步：目标与源完全一致（目标多余文件会先列出确认，再移到回收站）",
                     font=(FONT, 8), fg="#666").pack(anchor=tk.W)
            tk.Label(mf, text="增量同步：只把源文件夹的新文件复制到目标（不删除、不覆盖目标已有文件）",
                     font=(FONT, 8), fg="#666").pack(anchor=tk.W)

            lf = tk.Frame(self.root)
            lf.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)
            cols = ("源目录", "目标目录", "同步模式")
            self.tree = ttk.Treeview(lf, columns=cols, show="headings", height=8)
            for c, w in zip(cols, (300, 300, 100)):
                self.tree.heading(c, text=c)
                self.tree.column(c, width=w)
            sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
            self.tree.configure(yscrollcommand=sb.set)
            self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            sb.pack(side=tk.RIGHT, fill=tk.Y)

            b1 = tk.Frame(self.root)
            b1.pack(pady=5)
            for text, cmd, bg in (("➕ 添加同步任务", self.add_pair, BRAND),
                                  ("✏️ 修改选中任务", self.edit_pair, "#555"),
                                  ("🗑 删除选中任务", self.delete_pair, "#555")):
                tk.Button(b1, text=text, command=cmd, bg=bg, fg="white", font=(FONT, 10),
                          width=15, cursor="hand2").pack(side=tk.LEFT, padx=5)

            b2 = tk.Frame(self.root)
            b2.pack(pady=10)
            self.sync_all_btn = tk.Button(b2, text="▶ 执行全部同步", command=self.sync_all, bg=BRAND,
                                          fg="white", font=(FONT, 11, "bold"), width=18, cursor="hand2")
            self.sync_all_btn.pack(side=tk.LEFT, padx=5)
            self.sync_selected_btn = tk.Button(b2, text="▶ 执行选中同步", command=self.sync_selected,
                                               bg=BRAND, fg="white", font=(FONT, 11), width=18, cursor="hand2")
            self.sync_selected_btn.pack(side=tk.LEFT, padx=5)
            tk.Button(b2, text="📄 查看错误详情", command=self.show_errors, bg="#555", fg="white",
                      font=(FONT, 10), width=14, cursor="hand2").pack(side=tk.LEFT, padx=5)

            self.progress = ttk.Progressbar(self.root, mode="indeterminate")
            self.progress.pack(pady=5, padx=20, fill=tk.X)
            self.status_label = tk.Label(self.root, text="就绪", font=(FONT, 9), fg="#666")
            self.status_label.pack(pady=5)

            ff = tk.Frame(self.root, bg="#f5f5f5", relief=tk.RIDGE, bd=1)
            ff.pack(side=tk.BOTTOM, fill=tk.X, pady=5, padx=20)
            tk.Label(ff, text="baffox.com", font=(FONT, 10), fg=BRAND, bg="#f5f5f5").pack(pady=5)
            self.refresh_tree()

        def refresh_tree(self):
            self.tree.delete(*self.tree.get_children())
            for p in self.sync_pairs:
                mode = "完全同步" if p.get("mode") == "full" else "增量同步"
                self.tree.insert("", tk.END, values=(p["source"], p["target"], mode))

        def _pair_dialog(self, title, pair=None, idx=None):
            d = tk.Toplevel(self.root)
            d.title(title)
            d.geometry("550x320")
            d.resizable(False, False)
            d.transient(self.root)
            pair = pair or {}
            vars_ = {}
            for key, label, pad in (("source", "源目录：", 15), ("target", "目标目录：", 10)):
                tk.Label(d, text=label, font=(FONT, 10)).pack(pady=(pad, 0))
                v = tk.StringVar(value=pair.get(key, ""))
                fr = tk.Frame(d)
                fr.pack(pady=5, padx=20, fill=tk.X)
                tk.Entry(fr, textvariable=v, font=(FONT, 9)).pack(side=tk.LEFT, fill=tk.X, expand=True)

                def browse(v=v):
                    p = filedialog.askdirectory(parent=d)
                    if p:
                        v.set(os.path.normpath(p))
                tk.Button(fr, text="浏览", command=browse, font=(FONT, 9)).pack(side=tk.LEFT, padx=5)
                vars_[key] = v
            mode_var = tk.StringVar(value=pair.get("mode", "incremental"))
            tk.Label(d, text="同步模式：", font=(FONT, 10)).pack(pady=(10, 0))
            mf = tk.Frame(d)
            mf.pack(pady=5)
            tk.Radiobutton(mf, text="完全同步（目标=源）", variable=mode_var, value="full",
                           font=(FONT, 9)).pack(anchor=tk.W)
            tk.Radiobutton(mf, text="增量同步（只添加新文件）", variable=mode_var, value="incremental",
                           font=(FONT, 9)).pack(anchor=tk.W)

            def save():
                src, tgt = vars_["source"].get().strip(), vars_["target"].get().strip()
                err = validate_pair(src, tgt)
                if err:
                    messagebox.showwarning("提示", err, parent=d)
                    return
                new = {"source": src, "target": tgt, "mode": mode_var.get()}
                if idx is None:
                    self.sync_pairs.append(new)
                else:
                    self.sync_pairs[idx] = new
                self.save_settings()
                self.refresh_tree()
                d.destroy()
            tk.Button(d, text="保存", command=save, bg=BRAND, fg="white", font=(FONT, 10),
                      width=10).pack(pady=15)

        def _selected_index(self):
            sel = self.tree.selection()
            if not sel:
                messagebox.showwarning("提示", "请先选中一个任务")
                return None
            return self.tree.index(sel[0])

        def add_pair(self):
            self._pair_dialog("添加同步任务")

        def edit_pair(self):
            idx = self._selected_index()
            if idx is not None:
                self._pair_dialog("修改同步任务", self.sync_pairs[idx], idx)

        def delete_pair(self):
            idx = self._selected_index()
            if idx is None:
                return
            if messagebox.askyesno("确认删除", "确定要删除这个同步任务吗？\n（不会删除文件，只删除任务记录）"):
                del self.sync_pairs[idx]
                self.save_settings()
                self.refresh_tree()
                self.status_label.config(text="任务已删除")

        def sync_all(self):
            if not self.sync_pairs:
                messagebox.showwarning("提示", "没有同步任务，请先添加")
                return
            self.run_sync(list(self.sync_pairs))

        def sync_selected(self):
            idx = self._selected_index()
            if idx is not None:
                self.run_sync([self.sync_pairs[idx]])

        def _set_busy(self, busy, msg=""):
            self.running = busy
            state = tk.DISABLED if busy else tk.NORMAL
            self.sync_all_btn.config(state=state)
            self.sync_selected_btn.config(state=state)
            (self.progress.start if busy else self.progress.stop)()
            if msg:
                self.status_label.config(text=msg)

        def run_sync(self, pairs):
            if self.running:
                messagebox.showwarning("提示", "正在同步中，请稍候...")
                return
            self._set_busy(True, "正在分析差异...")

            def work():
                plans = [plan_sync(p["source"], p["target"], p.get("mode", "incremental")) for p in pairs]
                self.root.after(0, self._confirm_and_execute, plans)
            threading.Thread(target=work, daemon=True).start()

        def _confirm_and_execute(self, plans):
            deletions = [(p["target"], r) for p in plans for r in p["deletions"]]
            do_delete = True
            if deletions:
                do_delete = self._preview_deletions(deletions)
                if do_delete is None:
                    self._set_busy(False, "已取消同步")
                    return

            def progress(msg):
                self.root.after(0, self.status_label.config, {"text": msg})

            def work():
                tot = {"copied": 0, "deleted": 0, "skipped": 0, "errors": [], "trash_fallback": 0}
                for plan in plans:
                    r = execute_plan(plan, do_delete=do_delete, progress=progress)
                    for k in ("copied", "deleted", "skipped", "trash_fallback"):
                        tot[k] += r[k]
                    tot["errors"] += r["errors"]
                self.root.after(0, self._sync_finished, tot)
            threading.Thread(target=work, daemon=True).start()

        def _preview_deletions(self, deletions):
            """返回 True=同步并删除, False=只复制不删除, None=取消。"""
            d = tk.Toplevel(self.root)
            d.title("确认删除目标中多余的文件")
            d.geometry("720x460")
            d.transient(self.root)
            d.grab_set()
            tk.Label(d, text=f"完全同步将删除目标目录中 {len(deletions)} 个多余的文件/文件夹"
                             f"（会放进回收站，可以恢复）：", font=(FONT, 10), fg="#c00").pack(pady=8)
            fr = tk.Frame(d)
            fr.pack(fill=tk.BOTH, expand=True, padx=10)
            lb = tk.Listbox(fr, font=(FONT, 9))
            sb = ttk.Scrollbar(fr, orient=tk.VERTICAL, command=lb.yview)
            lb.configure(yscrollcommand=sb.set)
            lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            sb.pack(side=tk.RIGHT, fill=tk.Y)
            for tgt, rel in deletions:
                lb.insert(tk.END, os.path.join(tgt, rel))
            result = {"v": None}

            def choose(v):
                result["v"] = v
                d.destroy()
            bf = tk.Frame(d)
            bf.pack(pady=10)
            tk.Button(bf, text="确认同步并删除", command=lambda: choose(True), bg="#c00", fg="white",
                      font=(FONT, 10), width=16).pack(side=tk.LEFT, padx=5)
            tk.Button(bf, text="只复制，不删除", command=lambda: choose(False), bg="#555", fg="white",
                      font=(FONT, 10), width=16).pack(side=tk.LEFT, padx=5)
            tk.Button(bf, text="取消", command=lambda: choose(None), font=(FONT, 10),
                      width=10).pack(side=tk.LEFT, padx=5)
            d.protocol("WM_DELETE_WINDOW", lambda: choose(None))
            self.root.wait_window(d)
            return result["v"]

        def _sync_finished(self, tot):
            self._set_busy(False)
            summary = f"复制: {tot['copied']} | 跳过: {tot['skipped']} | 删除: {tot['deleted']}"
            if tot["trash_fallback"]:
                summary += f"\n（{tot['trash_fallback']} 项无法进回收站，已移到目标目录下的 {TRASH_DIR_NAME} 文件夹）"
            self.last_errors = tot["errors"]
            if tot["errors"]:
                summary += f" | 错误: {len(tot['errors'])}"
                try:
                    write_error_log(self.log_path, tot["errors"])
                    summary += f"\n错误详情已保存到：{self.log_path}"
                except OSError:
                    pass
            self.status_label.config(text=summary.split("\n")[0])
            if tot["errors"]:
                if messagebox.askyesno("同步完成（有错误）", summary + "\n\n现在查看错误详情吗？"):
                    self.show_errors()
            else:
                messagebox.showinfo("同步完成", summary)

        def show_errors(self):
            d = tk.Toplevel(self.root)
            d.title("错误详情")
            d.geometry("760x420")
            txt = tk.Text(d, font=(FONT, 9), wrap=tk.NONE)
            txt.pack(fill=tk.BOTH, expand=True)
            if self.last_errors:
                body = "本次同步的错误：\n" + "\n".join(self.last_errors)
            elif os.path.exists(self.log_path):
                with open(self.log_path, encoding="utf-8", errors="replace") as f:
                    body = f.read()[-20000:]
            else:
                body = "暂无错误记录。"
            txt.insert("1.0", body + f"\n\n日志文件：{self.log_path}")
            txt.config(state=tk.DISABLED)

    root = tk.Tk()
    SyncToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()

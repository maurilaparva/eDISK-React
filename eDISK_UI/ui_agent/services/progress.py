"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: progress.py
@Time: 10/16/25; 11:27 AM
"""
# ui_agent/services/progress.py

PROGRESS_STORE = {}


def set_progress(run_id: str, message: str):
    """保存每个任务的进度"""
    msgs = PROGRESS_STORE.setdefault(run_id, [])
    msgs.append(message)
    print(f"[PROGRESS][{run_id}] {message}")


def get_progress(run_id: str):
    """返回任务进度"""
    return PROGRESS_STORE.get(run_id, [])

# sitecustomize.py — 绕过 /usr/lib/python3/dist-packages/distlib-0.3.4.egg-info
# 目录块损坏（ext4 目录校验和失败 → OSError Errno 74 EBADMSG）导致的
# "ros2 CLI 一启动就崩" 的问题。
#
# 背景（2026-10-11）：
#   rootfs /dev/mmcblk1p2 上 inode #918109 的目录块校验和坏了，内核报
#     EXT4-fs error ... Directory block failed checksum
#   ros2cli 启动时调用 importlib_metadata.entry_points()（注意：ros2 用的是
#   /usr/lib/python3/dist-packages 下的 backport 版，不是 stdlib），它会遍历
#   所有发行包的 entry_points.txt，碰到这个坏目录就抛 OSError，于是
#   ros2 launch / ros2 run / ros2 node list 全部在启动前崩掉。
#   损坏目录无法 rm/遍历，真正的修复要在未挂载状态下 e2fsck。
#
# 本文件只做两件事（都不改系统文件）：
#   1) 给所有带 read_text 的发行包类加保护：读不出来就当作“没有”
#   2) 过滤 distributions()：元数据读不出来的发行包直接跳过
#   —— 用"扫描模块命名空间"的方式实现，所以对 stdlib 版和 backport 版都成立。
#
# ★ 这是绕过，不是修复。文件系统仍需在方便时做 e2fsck。
#
# 用法：export PYTHONPATH=/home/sunrise/robot_ws/tools/pyfix:$PYTHONPATH
#   （start_library_gui.sh 的 ROS_ENV_HEAD 已包含本目录）

_FLAG = '_rdk_pyfix_safe_read'


def _make_safe(orig):
    def safe_read_text(self, filename):
        try:
            return orig(self, filename)
        except OSError:
            return None          # 元数据读不出来 -> 当作“没有 entry points”
    return safe_read_text


def _patch_module(module, report):
    # 1) 所有带 read_text 的类都加保护
    for attr in dir(module):
        try:
            cls = getattr(module, attr)
        except Exception:
            continue
        if not isinstance(cls, type) or getattr(cls, _FLAG, False):
            continue
        orig = getattr(cls, 'read_text', None)
        if not callable(orig):
            continue
        try:
            setattr(cls, 'read_text', _make_safe(orig))
            setattr(cls, _FLAG, True)
            report.append(attr)
        except Exception:
            pass

    # 2) distributions() 过滤掉读不出元数据的发行包
    orig_dist = getattr(module, 'distributions', None)
    if callable(orig_dist) and not getattr(orig_dist, _FLAG, False):
        def safe_distributions(*a, **kw):
            for d in orig_dist(*a, **kw):
                try:
                    list(d.entry_points)
                except OSError:
                    continue         # 坏发行包 -> 跳过(本体只剩 entry_points 不可读)
                yield d
        safe_distributions.__name__ = 'distributions'
        setattr(safe_distributions, _FLAG, True)
        module.distributions = safe_distributions
        report.append(distributions='patched')


def _install():
    for modname in ('importlib_metadata', 'importlib.metadata'):
        try:
            mod = __import__(modname, fromlist=['distributions'])
        except Exception:
            continue
        try:
            _patch_module(mod, [])
        except Exception:
            pass


_install()

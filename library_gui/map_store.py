#!/usr/bin/env python3
"""map_store.py —— 地图仓库 + 历史回溯（GUI「地图」模块的后端）

目录约定（沿用项目原有布局, 不改动导航栈的读取路径）
    当前地图 = 导航栈 / 地图视图真正读的那一份:
        maps/library.yaml
        maps/library.pgm
        maps/library.posegraph      (可选, slam_toolbox 位姿图)
        maps/library.data           (可选, slam_toolbox 数据)
        maps/bookmarks.json         (可选, 书位锚点)

    历史版本 = 每次「保存」把当时最新的 SLAM 建图结果整包存一份:
        maps/history/<版本号>/
            meta.json + 上面那几个文件的副本
        maps/history/index.json     (索引缓存; 坏了能从目录重建)

安全约定
    * 保存只新增目录, 绝不覆盖任何历史版本;
    * 回溯(restore)会改写「当前地图」, 所以**先把当前地图自动另存为一个版本**
      再覆盖 —— 于是回溯本身也能再回溯, 不会把地图弄丢;
    * 删除只作用于 history/ 下的版本目录, 且有目录穿越保护。

本模块不依赖 Qt / ROS, 可以直接在板端跑单测(见文件末尾 __main__)。
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime

DEFAULT_MAPS_DIR = '/home/sunrise/robot_ws/maps'
DEFAULT_BASE = 'library'
DEFAULT_SAVE_SCRIPT = '/home/sunrise/robot_ws/scripts/save_map.sh'

# 一个「地图版本」由哪些文件组成（.yaml/.pgm 是必需项, 后两个可选）
BUNDLE_SUFFIXES = ('.yaml', '.pgm', '.posegraph', '.data')
BOOKMARKS_NAME = 'bookmarks.json'


# ----------------------------------------------------------------------
# 小工具（不引第三方依赖: 地图 yaml 是极简 key: value, PGM 只读头部）
# ----------------------------------------------------------------------
def _read_yaml_simple(path):
    cfg = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or ':' not in line:
                    continue
                k, _, v = line.partition(':')
                cfg[k.strip()] = v.strip()
    except OSError:
        pass
    return cfg


def _parse_origin(text):
    """'[ -3.73, -3.47, 0 ]' -> [-3.73, -3.47, 0.0]"""
    vals = []
    for x in re.findall(r'-?\d+(?:\.\d+)?', text or ''):
        try:
            vals.append(float(x))
        except ValueError:
            pass
    return vals[:3]


def _pgm_size(path):
    """读 P5 PGM 的宽高, 失败返回 (0, 0)。"""
    try:
        with open(path, 'rb') as f:
            raw = f.read(256)
        idx = raw.find(b'P5')
        if idx < 0:
            return 0, 0
        parts = raw[idx:].split(b'\n', 3)
        wh = parts[1].split()
        return int(wh[0]), int(wh[1])
    except Exception:
        return 0, 0


def _md5(path):
    h = hashlib.md5()
    try:
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
    except OSError:
        return ''
    return h.hexdigest()


def _now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _count_bookmarks(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return len(json.load(f).get('books', {}) or {})
    except Exception:
        return 0


class MapStore:
    """地图版本仓库。所有操作都返回 {'ok': bool, 'msg': str, ...}。"""

    def __init__(self, maps_dir=DEFAULT_MAPS_DIR, base=DEFAULT_BASE):
        self.maps_dir = maps_dir
        self.base = base
        self.history_dir = os.path.join(maps_dir, 'history')
        self.index_path = os.path.join(self.history_dir, 'index.json')

    # ------------------------------------------------------------------
    # 当前地图
    # ------------------------------------------------------------------
    def current_paths(self):
        """当前地图实际存在的文件: {文件名: 绝对路径}"""
        out = {}
        for suf in BUNDLE_SUFFIXES:
            name = self.base + suf
            p = os.path.join(self.maps_dir, name)
            if os.path.isfile(p):
                out[name] = p
        bm = os.path.join(self.maps_dir, BOOKMARKS_NAME)
        if os.path.isfile(bm):
            out[BOOKMARKS_NAME] = bm
        return out

    def current_info(self):
        yml = os.path.join(self.maps_dir, self.base + '.yaml')
        pgm = os.path.join(self.maps_dir, self.base + '.pgm')
        cfg = _read_yaml_simple(yml)
        w, h = _pgm_size(pgm)
        res = None
        try:
            res = float(cfg['resolution'])
        except (KeyError, ValueError, TypeError):
            res = None
        mtime = os.path.getmtime(pgm) if os.path.isfile(pgm) else 0
        return {
            'exists': os.path.isfile(pgm) or os.path.isfile(yml),
            'yaml': yml,
            'pgm': pgm,
            'resolution': res,
            'origin': _parse_origin(cfg.get('origin', '')),
            'width': w,
            'height': h,
            'bookmarks': _count_bookmarks(
                os.path.join(self.maps_dir, BOOKMARKS_NAME)),
            'pgm_md5': _md5(pgm) if os.path.isfile(pgm) else '',
            'files': sorted(os.path.basename(p)
                            for p in self.current_paths().values()),
            'mtime': mtime,
            'time': datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                    if mtime else '-',
        }

    def slam_running(self):
        """只读扫 /proc 判断 slam_toolbox 是否在跑（不启 ROS, 很快）。"""
        for pid in os.listdir('/proc'):
            if not pid.isdigit():
                continue
            try:
                with open(f'/proc/{pid}/cmdline', 'rb') as f:
                    cl = f.read().decode('utf-8', 'ignore')
            except OSError:
                continue
            if 'slam_toolbox' in cl:
                return True
        return False

    def refresh_from_slam(self, timeout=120, script=DEFAULT_SAVE_SCRIPT):
        """让 slam_toolbox 把当前建图结果写回 maps/（调项目原有 save_map.sh）。

        返回 (ok, msg)。SLAM 没在跑时 ok=False, 调用方应回退成
        「直接给现有 maps/library.* 打一个版本」。
        """
        if not os.path.isfile(script):
            return False, f'找不到存图脚本 {script}'
        pgm = os.path.join(self.maps_dir, self.base + '.pgm')
        before = os.path.getmtime(pgm) if os.path.isfile(pgm) else 0
        try:
            r = subprocess.run(['bash', script, self.base],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT,
                               text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, f'调用 save_map.sh 超时（{timeout}s）'
        except Exception as e:
            return False, f'调用 save_map.sh 失败：{e}'
        after = os.path.getmtime(pgm) if os.path.isfile(pgm) else 0
        lines = (r.stdout or '').strip().splitlines()
        tail = ' / '.join(lines[-3:]) if lines else f'退出码 {r.returncode}'
        if after > before:
            return True, f'已从 SLAM 抓取最新建图结果（{tail}）'
        return False, f'SLAM 未产出新地图（{tail}）'

    # ------------------------------------------------------------------
    # 历史版本
    # ------------------------------------------------------------------
    def _new_version_id(self):
        stamp = time.strftime('%Y%m%d-%H%M%S')
        vid, n = stamp, 1
        while os.path.isdir(os.path.join(self.history_dir, vid)):
            n += 1
            vid = f'{stamp}-{n}'
        return vid

    def version_dir(self, version_id):
        return os.path.join(self.history_dir, version_id)

    def version_pgm_path(self, version_id):
        return os.path.join(self.version_dir(version_id), self.base + '.pgm')

    def save_current(self, label='手动保存', note='', source='manual'):
        """把「当前地图」整包存成一个新版本。只新增, 不覆盖。"""
        files = self.current_paths()
        if self.base + '.pgm' not in files and self.base + '.yaml' not in files:
            return {'ok': False,
                    'msg': f'当前地图不存在：{self.maps_dir}/{self.base}.(yaml|pgm)'}
        try:
            os.makedirs(self.history_dir, exist_ok=True)
            vid = self._new_version_id()
            vdir = self.version_dir(vid)
            os.makedirs(vdir, exist_ok=True)
            copied = []
            for name, src in files.items():
                shutil.copy2(src, os.path.join(vdir, name))
                copied.append(name)
        except Exception as e:
            return {'ok': False, 'msg': f'保存失败：{e}'}

        info = self.current_info()
        meta = {
            'id': vid,
            'label': (label or '未命名').strip(),
            'note': note or '',
            'time': _now_str(),
            'source': source,
            'files': sorted(copied),
            'width': info['width'],
            'height': info['height'],
            'resolution': info['resolution'],
            'origin': info['origin'],
            'bookmarks': info['bookmarks'],
            'pgm_md5': info['pgm_md5'],
            'bytes': sum(os.path.getsize(os.path.join(vdir, n))
                         for n in copied),
        }
        try:
            with open(os.path.join(vdir, 'meta.json'), 'w',
                      encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except OSError as e:
            return {'ok': False, 'msg': f'写 meta.json 失败：{e}'}

        self.list_versions()          # 顺手刷新索引
        return {'ok': True,
                'msg': f'已保存版本 {vid}（{meta["label"]}）',
                'version': meta}

    def _scan_version(self, vid):
        vdir = self.version_dir(vid)
        meta_path = os.path.join(vdir, 'meta.json')
        meta = {}
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f) or {}
            except Exception:
                meta = {}
        # meta 缺失/损坏时, 直接从文件补全
        if not meta.get('files'):
            names = sorted(n for n in os.listdir(vdir) if n != 'meta.json')
            meta['files'] = names
        pgm = self.version_pgm_path(vid)
        if not meta.get('pgm_md5'):
            meta['pgm_md5'] = _md5(pgm) if os.path.isfile(pgm) else ''
        if not meta.get('width'):
            w, h = _pgm_size(pgm)
            meta['width'], meta['height'] = w, h
        if not meta.get('resolution'):
            cfg = _read_yaml_simple(
                os.path.join(vdir, self.base + '.yaml'))
            try:
                meta['resolution'] = float(cfg.get('resolution'))
            except (TypeError, ValueError):
                meta['resolution'] = None
        if not meta.get('bookmarks'):
            meta['bookmarks'] = _count_bookmarks(
                os.path.join(vdir, BOOKMARKS_NAME))
        meta.setdefault('id', vid)
        meta.setdefault('label', vid)
        meta.setdefault('note', '')
        meta.setdefault('source', 'unknown')
        if not meta.get('time'):
            t = os.path.getmtime(vdir)
            meta['time'] = datetime.fromtimestamp(t).strftime(
                '%Y-%m-%d %H:%M:%S')
        if not meta.get('bytes'):
            try:
                meta['bytes'] = sum(
                    os.path.getsize(os.path.join(vdir, n))
                    for n in os.listdir(vdir))
            except OSError:
                meta['bytes'] = 0
        meta['dir'] = vdir
        return meta

    def list_versions(self, write_index=True):
        """列出所有历史版本, 最新的在前。顺带算出哪一个是「当前生效」的。"""
        if not os.path.isdir(self.history_dir):
            versions = []
        else:
            vids = []
            for name in os.listdir(self.history_dir):
                if name == 'index.json':
                    continue
                if os.path.isdir(os.path.join(self.history_dir, name)):
                    vids.append(name)
            versions = [self._scan_version(v) for v in sorted(vids, reverse=True)]

        # 「当前生效」按内容(pgm md5)判定; 内容相同的多个版本里只标记最新那个
        cur_md5 = self.current_info()['pgm_md5']
        marked = False
        for v in versions:                      # versions 已按最新在前排序
            v['is_current'] = False
            if cur_md5 and not marked and v.get('pgm_md5') == cur_md5:
                v['is_current'] = True
                marked = True

        if write_index:
            try:
                os.makedirs(self.history_dir, exist_ok=True)
                with open(self.index_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'base': self.base,
                        'maps_dir': self.maps_dir,
                        'updated': _now_str(),
                        'count': len(versions),
                        'versions': versions,
                    }, f, ensure_ascii=False, indent=2)
            except OSError:
                pass
        return versions

    def restore(self, version_id, backup=True):
        """把某个历史版本回溯成「当前地图」。默认先自动备份当前地图。"""
        vdir = self.version_dir(version_id)
        if not os.path.isdir(vdir):
            return {'ok': False, 'msg': f'版本不存在：{version_id}'}

        info = self.current_info()
        if info['exists'] and info['pgm_md5']:
            vpgm = self.version_pgm_path(version_id)
            if os.path.isfile(vpgm) and _md5(vpgm) == info['pgm_md5']:
                return {'ok': True, 'msg': f'{version_id} 就是当前地图，无需回溯',
                        'restored': [], 'backup': None}

        backup_id = None
        if backup and info['exists']:
            r = self.save_current(
                label='回溯前自动备份',
                note=f'准备回溯到 {version_id}，先自动保存当前地图',
                source='auto-backup')
            if r.get('ok'):
                backup_id = r['version']['id']

        restored = []
        try:
            for name in sorted(os.listdir(vdir)):
                if name == 'meta.json':
                    continue
                if name == BOOKMARKS_NAME:
                    dst = os.path.join(self.maps_dir, BOOKMARKS_NAME)
                else:
                    stem, ext = os.path.splitext(name)
                    if stem != self.base or ext not in BUNDLE_SUFFIXES:
                        continue
                    dst = os.path.join(self.maps_dir, name)
                shutil.copy2(os.path.join(vdir, name), dst)
                restored.append(name)
        except Exception as e:
            return {'ok': False, 'msg': f'回溯失败：{e}',
                    'restored': restored, 'backup': backup_id}

        self.list_versions()
        tail = f'（原地图已自动备份为 {backup_id}）' if backup_id else ''
        return {'ok': True, 'msg': f'已回溯到 {version_id}{tail}',
                'restored': sorted(restored), 'backup': backup_id}

    def delete(self, version_id):
        """删除一个历史版本（只允许删 history/ 下的目录）。"""
        history_real = os.path.realpath(self.history_dir)
        target = os.path.realpath(self.version_dir(version_id))
        if not target.startswith(history_real + os.sep) or \
                not os.path.isdir(target):
            return {'ok': False, 'msg': f'版本不存在或路径非法：{version_id}'}
        try:
            shutil.rmtree(target)
        except Exception as e:
            return {'ok': False, 'msg': f'删除失败：{e}'}
        self.list_versions()
        return {'ok': True, 'msg': f'已删除版本 {version_id}'}

    def prune(self, keep=10):
        """只保留最新的 keep 个版本, 其余删掉。返回删除数量。"""
        versions = self.list_versions()
        removed = 0
        for v in versions[keep:]:
            if v.get('is_current'):
                continue
            if self.delete(v['id']).get('ok'):
                removed += 1
        return removed


if __name__ == '__main__':
    import sys

    store = MapStore()
    print('maps_dir   =', store.maps_dir)
    print('base       =', store.base)
    print('SLAM 在跑  =', store.slam_running())
    info = store.current_info()
    print('当前地图   =', info['width'], 'x', info['height'],
          'res=', info['resolution'], 'origin=', info['origin'],
          '书位=', info['bookmarks'], '文件=', info['files'])
    vs = store.list_versions()
    print(f'历史版本数 = {len(vs)}')
    for v in vs[:10]:
        print('   ', v['id'], v.get('label'), v.get('time'),
              f"{v.get('width')}x{v.get('height')}",
              '当前' if v.get('is_current') else '')

    if '--save' in sys.argv:
        label = sys.argv[sys.argv.index('--save') + 1] \
            if len(sys.argv) > sys.argv.index('--save') + 1 else '命令行保存'
        print(store.save_current(label=label, source='cli'))

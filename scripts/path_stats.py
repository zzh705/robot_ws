import json, math, sys

p = sys.argv[1] if len(sys.argv) > 1 else '/home/sunrise/robot_ws/logs/recorded_path.json'
w = json.load(open(p))['waypoints']
n = len(w)
length = sum(math.hypot(w[i + 1]['x'] - w[i]['x'], w[i + 1]['y'] - w[i]['y'])
             for i in range(n - 1))
xs = [q['x'] for q in w]
ys = [q['y'] for q in w]
turns = sum(abs(w[i + 1]['yaw'] - w[i]['yaw']) for i in range(n - 1))

print('路点数 : %d' % n)
print('总里程 : %.2f m' % length)
print('X 范围: %.2f ~ %.2f  (%.2f m)' % (min(xs), max(xs), max(xs) - min(xs)))
print('Y 范围: %.2f ~ %.2f  (%.2f m)' % (min(ys), max(ys), max(ys) - min(ys)))
print('起点  : (%.3f, %.3f) yaw=%.1f deg' % (w[0]['x'], w[0]['y'], math.degrees(w[0]['yaw'])))
print('终点  : (%.3f, %.3f) yaw=%.1f deg' % (w[-1]['x'], w[-1]['y'], math.degrees(w[-1]['yaw'])))
print('累计转向: %.0f deg' % math.degrees(turns))
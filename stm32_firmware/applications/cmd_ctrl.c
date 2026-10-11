#include <rtthread.h>
#include <stdlib.h>
#include <string.h>

#include "motion_ctrl.h"
#include "pwm_test.h"
#include "pulse.h"

#ifdef RT_USING_FINSH
#include <finsh.h>

/* 测试单个电机 */
static int motor_test(int argc, char **argv)
{
    if (argc != 3)
    {
        rt_kprintf("usage: motor_test <motor_id(1-4)> <speed_percent(-100 to 100)>\n");
        return -1;
    }
    
    int motor_id = atoi(argv[1]);
    float speed = atof(argv[2]);
    
    if (motor_id < 1 || motor_id > 4)
    {
        rt_kprintf("Invalid motor ID. Must be between 1 and 4.\n");
        return -1;
    }
    
    if (speed < -100.0f || speed > 100.0f)
    {
        rt_kprintf("Invalid speed. Must be between -100 and 100.\n");
        return -1;
    }
    
    rt_kprintf("Testing motor %d at %d%%\n", motor_id, (int)speed);
    motor_output(motor_id, speed);
    return 0;
}
MSH_CMD_EXPORT(motor_test, test individual motor);

/* 测试所有电机 */
static int motor_test_all(int argc, char **argv)
{
    if (argc != 2)
    {
        rt_kprintf("usage: motor_test_all <speed_percent(-100 to 100)>\n");
        return -1;
    }
    
    float speed = atof(argv[1]);
    
    if (speed < -100.0f || speed > 100.0f)
    {
        rt_kprintf("Invalid speed. Must be between -100 and 100.\n");
        return -1;
    }
    
    rt_kprintf("Testing all motors at %d%%\n", (int)speed);
    for (int i = 1; i <= 4; i++) {
        motor_output(i, speed);
    }
    return 0;
}
MSH_CMD_EXPORT(motor_test_all, test all motors);

/* 运行时设置电机方向系数（±1），立即生效，无需重烧录
 * 用法: m_dir <d1> <d2> <d3> <d4>   例: m_dir 1 1 -1 -1
 */
static int m_dir(int argc, char **argv)
{
    float d[4];

    if (argc == 1)
    {
        motion_get_motor_direction(d);
        rt_kprintf("motor dirs: M1=%+d M2=%+d M3=%+d M4=%+d\n",
                   (int)d[0], (int)d[1], (int)d[2], (int)d[3]);
        return 0;
    }

    if (argc != 5)
    {
        rt_kprintf("usage: m_dir | m_dir <d1> <d2> <d3> <d4>  (each +1 or -1)\n");
        return -1;
    }

    for (int i = 0; i < 4; i++)
    {
        d[i] = (float)atof(argv[i + 1]);
        if (d[i] != 1.0f && d[i] != -1.0f)
        {
            rt_kprintf("dir must be +1 or -1, got %.0f\n", d[i]);
            return -1;
        }
    }

    if (motion_set_motor_direction(d[0], d[1], d[2], d[3]) != RT_EOK)
    {
        rt_kprintf("set dir failed\n");
        return -1;
    }
    rt_kprintf("motor dirs set: M1=%+d M2=%+d M3=%+d M4=%+d\n",
               (int)d[0], (int)d[1], (int)d[2], (int)d[3]);
    return 0;
}
MSH_CMD_EXPORT(m_dir, set motor dirs: m_dir d1 d2 d3 d4 (+1/-1));

/* 开环/闭环切换：ol 1 关闭环（可配合 motor_test 逐个测电机），ol 0 恢复 */
static int ol(int argc, char **argv)
{
    if (argc != 2)
    {
        rt_kprintf("usage: ol <0|1>  (1=open loop, 0=closed loop)\n");
        return -1;
    }
    int v = atoi(argv[1]);
    if (v != 0 && v != 1)
    {
        rt_kprintf("arg must be 0 or 1\n");
        return -1;
    }
    motion_set_openloop(v == 1 ? RT_TRUE : RT_FALSE);
    rt_kprintf("control loop: %s\n", v ? "OPEN" : "CLOSED");
    return 0;
}
MSH_CMD_EXPORT(ol, open/close control loop: ol 0|1);

/* 继续获取当前速度 */
static int get_speeds(int argc, char **argv)
{
    RT_UNUSED(argc);
    RT_UNUSED(argv);
    
    float v1, v2, v3, v4;
    if (motion_get_current_speeds(&v1, &v2, &v3, &v4) == RT_EOK)
    {
        rt_kprintf("Current speeds (cm/s):\n");
        rt_kprintf("  M1 (left front):  %d  (x0.01)\n", (int)(v1 * 100.0f));
        rt_kprintf("  M2 (left rear):   %d  (x0.01)\n", (int)(v2 * 100.0f));
        rt_kprintf("  M3 (right front): %d  (x0.01)\n", (int)(v3 * 100.0f));
        rt_kprintf("  M4 (right rear):  %d  (x0.01)\n", (int)(v4 * 100.0f));
    }
    else
    {
        rt_kprintf("Failed to get current speeds\n");
    }
    return 0;
}
MSH_CMD_EXPORT(get_speeds, get current wheel speeds);

/* 前后移动指定距离（cm）——阻塞 */
static int move_spd(int argc, char **argv)
{
    if (argc != 2)
    {
        rt_kprintf("usage: move_spd <cm_per_s>\n");
        return -1;
    }
    float v = atof(argv[1]);

    /* 四轮前进：速度相同 */
    rt_kprintf("Moving all wheels at speed %d cm/s\n", (int)v);
    motion_request_wheels(v, v, v, v);
    return 0;
}
MSH_CMD_EXPORT(move_spd, forward speed cm/s);

/* 左右平移（麦克纳姆标准） */
static int strafe_spd(int argc, char **argv)
{
    if (argc != 2)
    {
        rt_kprintf("usage: strafe_spd <cm_per_s>\n");
        return -1;
    }
    float v = atof(argv[1]);

    /* 标准麦轮横移速度分配 */
    rt_kprintf("Strafing at speed %d cm/s\n", (int)v);
    motion_request_wheels(+v, -v, -v, +v);
    return 0;
}
MSH_CMD_EXPORT(strafe_spd, strafe speed);

/* 停止 */
static int mstop(int argc, char **argv)
{
    RT_UNUSED(argc);
    RT_UNUSED(argv);
    rt_kprintf("Stopping all wheels\n");
    motion_request_wheels(0,0,0,0);
    return 0;
}
MSH_CMD_EXPORT(mstop, stop all wheels);

/* 编码器标定：读取四轮累计原始脉冲
 * 用法:
 *   enc_cal          读取并打印四轮累计脉冲
 *   enc_cal zero     将四轮计数清零
 *   enc_cal rev <N>  读取并按"每 N 圈"换算 counts/圈
 */
static int enc_cal(int argc, char **argv)
{
    rt_int32_t c[4];

    if (argc >= 2 && strcmp(argv[1], "zero") == 0)
    {
        pulse_clear_counts();
        rt_kprintf("encoder counts cleared\n");
        return 0;
    }

    pulse_get_raw_counts(c);

    if (argc >= 3 && strcmp(argv[1], "rev") == 0)
    {
        int n = atoi(argv[2]);
        if (n <= 0)
        {
            rt_kprintf("usage: enc_cal rev <N>\n");
            return -1;
        }
        rt_kprintf("counts/rev (N=%d): FL=%d RL=%d FR=%d RR=%d\n",
                   n, c[0] / n, c[1] / n, c[2] / n, c[3] / n);
        return 0;
    }

    rt_kprintf("FL=%d RL=%d FR=%d RR=%d\n", c[0], c[1], c[2], c[3]);
    return 0;
}
MSH_CMD_EXPORT(enc_cal, encoder calib: enc_cal | zero | rev <N>);

/* 在线整定四轮 PID
 * 用法:
 *   pid                       打印四轮 kp/ki/kd（数值 x1000）
 *   pid <0-3> <kp> <ki> <kd>  设置指定轮
 *   pid all   <kp> <ki> <kd>  设置全部四轮
 */
static int pid_cmd(int argc, char **argv)
{
    if (argc == 1)
    {
        for (int i = 0; i < 4; i++)
        {
            float kp, ki, kd;
            motion_get_pid(i, &kp, &ki, &kd);
            rt_kprintf("W%d kp=%d ki=%d kd=%d (x1000)\n",
                       i, (int)(kp * 1000.0f), (int)(ki * 1000.0f), (int)(kd * 1000.0f));
        }
        return 0;
    }

    if (argc != 5)
    {
        rt_kprintf("usage: pid | pid <0-3|all> <kp> <ki> <kd>\n");
        return -1;
    }

    float kp = (float)atof(argv[2]);
    float ki = (float)atof(argv[3]);
    float kd = (float)atof(argv[4]);

    if (strcmp(argv[1], "all") == 0)
    {
        for (int i = 0; i < 4; i++) motion_set_pid(i, kp, ki, kd);
        rt_kprintf("set all pid: kp=%d ki=%d kd=%d (x1000)\n",
                   (int)(kp * 1000.0f), (int)(ki * 1000.0f), (int)(kd * 1000.0f));
        return 0;
    }

    int idx = atoi(argv[1]);
    if (idx < 0 || idx > 3)
    {
        rt_kprintf("idx must be 0-3 or all\n");
        return -1;
    }
    motion_set_pid(idx, kp, ki, kd);
    rt_kprintf("set W%d pid: kp=%d ki=%d kd=%d (x1000)\n",
               idx, (int)(kp * 1000.0f), (int)(ki * 1000.0f), (int)(kd * 1000.0f));
    return 0;
}
MSH_CMD_EXPORT_ALIAS(pid_cmd, pid, pid tune: pid | pid <0-3|all> <kp> <ki> <kd>);

/* 打印四轮当前 PID 状态：目标速度、当前速度、PID 输出 PWM */
static int dbg_motor(int argc, char **argv)
{
    RT_UNUSED(argc);
    RT_UNUSED(argv);
    extern void motion_dbg_motor(void);
    motion_dbg_motor();
    return 0;
}
MSH_CMD_EXPORT(dbg_motor, debug motor pid state);

#endif /* RT_USING_FINSH */
#include "motion_ctrl.h"
#include "pulse.h"
#include "pwm_test.h"
#include <rtthread.h>
#include <math.h>
#include <string.h>

/* ======================================================================
 * 电机方向校正系数（唯一校正点）
 * 顺序：M1(左前), M2(左后), M3(右前), M4(右后)
 * 实测（开环+30%）：M1/M3 的 +PWM 朝车头，M2/M4 的 +PWM 朝车尾
 * → 前后电机反装，故 M2/M4 取 -1，保证四轮同向推车头
 * ====================================================================== */
static float g_motor_direction[4] = {
    +1.0f,  // M1: 左前轮 (+PWM=车头)
    -1.0f,  // M2: 左后轮 (+PWM=车尾，反转)
    +1.0f,  // M3: 右前轮 (+PWM=车头)
    -1.0f   // M4: 右后轮 (+PWM=车尾，反转)
};

static float g_vtx = 0.0f;
static float g_vty = 0.0f;
static float g_omega = 0.0f;
/* ======================================================================
 * 四轮独立 PID 参数（调参只需改这里）
 * ====================================================================== */
#define KP_W1  3.00f   // 增大比例系数以提高响应
#define KI_W1  0.30f   // 增加积分作用消除稳态误差
#define KD_W1  0.00f   // 微分作用抑制震荡

#define KP_W2  3.00f
#define KI_W2  0.30f
#define KD_W2  0.00f

#define KP_W3  3.00f
#define KI_W3  0.30f
#define KD_W3  0.00f

#define KP_W4  3.00f
#define KI_W4  0.30f
#define KD_W4  0.00f

/* ========== PID 结构体 ========== */
typedef struct {
    float kp, ki, kd;
    float integral;
    float prev_err;
    float out_min;
    float out_max;
} PID_TypeDef;

/* ======================================================================
 * PID 计算函数
 * 输入：目标速度、当前速度（单位：cm/s）
 * 输出：PWM 值（-100 ~ +100）
 * ====================================================================== */
static float PID_Compute(PID_TypeDef *pid, float target, float current)
{
   // rt_kprintf("[PID] Target: %.2f, Current: %.2f\n", target, current);
    
    // 当目标速度为0时，直接输出0并重置PID状态
    if (fabsf(target) < 0.001f) {
        pid->integral = 0;
        pid->prev_err = 0;
       // rt_kprintf("[PID] Target near zero, output 0\n");
        return 0.0f;
    }

    float err = target - current;
    pid->integral += err;
    
    // 积分限幅，防止积分饱和
    if (pid->integral > 100.0f) pid->integral = 100.0f;
    if (pid->integral < -100.0f) pid->integral = -100.0f;

    float derivative = err - pid->prev_err;
    float out = pid->kp * err + pid->ki * pid->integral + pid->kd * derivative;

    pid->prev_err = err;

    // 输出限幅
    if (out > pid->out_max) out = pid->out_max;
    if (out < pid->out_min) out = pid->out_min;
    
    // rt_kprintf("[PID] Err: %.2f, Integral: %.2f, Out: %.2f\n", err, pid->integral, out);

    return out;
}

static void PID_Init(PID_TypeDef *pid, float kp, float ki, float kd, float out_min, float out_max)
{
    pid->kp = kp;
    pid->ki = ki;
    pid->kd = kd;
    pid->integral = 0.0f;
    pid->prev_err = 0.0f;
    pid->out_min = out_min;
    pid->out_max = out_max;
}

/* ======================================================================
 * 控制结构体（含互斥锁保护）
 * ====================================================================== */
static struct {
    float v_target[4];
    float v_current[4];
    PID_TypeDef pid[4];
    rt_mutex_t lock;
} g_ctrl;

static ctrl_mode_t g_ctrl_mode = CTRL_MODE_INDEPENDENT;

/* 开环测试开关：置1时运动线程不输出任何 PWM，便于用 motor_test 逐个测电机 */
static rt_bool_t g_openloop = RT_FALSE;

/* ======================================================================
 * 设置控制模式（预留扩展）
 * ====================================================================== */
rt_err_t motion_set_control_mode(int mode)
{
    if (mode < CTRL_MODE_INDEPENDENT || mode > CTRL_MODE_UNIFIED)
        return -RT_ERROR;
    g_ctrl_mode = (ctrl_mode_t)mode;
    return RT_EOK;
}

/* 开环/闭环切换：enable=1 时运动线程只上报速度、不输出 PWM */
rt_err_t motion_set_openloop(rt_bool_t enable)
{
    rt_mutex_take(g_ctrl.lock, RT_WAITING_FOREVER);
    g_openloop = enable;
    rt_mutex_release(g_ctrl.lock);
    return RT_EOK;
}

/* ======================================================================
 * 运行时设置电机方向（安全接口）
 * ====================================================================== */
rt_err_t motion_set_motor_direction(float dir1, float dir2, float dir3, float dir4)
{
    if ((dir1 != 1.0f && dir1 != -1.0f) ||
        (dir2 != 1.0f && dir2 != -1.0f) ||
        (dir3 != 1.0f && dir3 != -1.0f) ||
        (dir4 != 1.0f && dir4 != -1.0f)) {
        return -RT_ERROR;
    }

    rt_mutex_take(g_ctrl.lock, RT_WAITING_FOREVER);
    g_motor_direction[0] = dir1;
    g_motor_direction[1] = dir2;
    g_motor_direction[2] = dir3;
    g_motor_direction[3] = dir4;
    rt_mutex_release(g_ctrl.lock);
    return RT_EOK;
}

/* 读取当前电机方向系数 */
rt_err_t motion_get_motor_direction(float d[4])
{
    if (!d) return -RT_ERROR;

    rt_mutex_take(g_ctrl.lock, RT_WAITING_FOREVER);
    d[0] = g_motor_direction[0];
    d[1] = g_motor_direction[1];
    d[2] = g_motor_direction[2];
    d[3] = g_motor_direction[3];
    rt_mutex_release(g_ctrl.lock);
    return RT_EOK;
}

/* ======================================================================
 * 设置目标速度（应用方向校正）
 * 单位：cm/s
 * ====================================================================== */
rt_err_t motion_request_wheels(float v1, float v2, float v3, float v4)
{
    rt_mutex_take(g_ctrl.lock, RT_WAITING_FOREVER);
    g_ctrl.v_target[0] = v1 * g_motor_direction[0]; // M1
    g_ctrl.v_target[1] = v2 * g_motor_direction[1]; // M2
    g_ctrl.v_target[2] = v3 * g_motor_direction[2]; // M3
    g_ctrl.v_target[3] = v4 * g_motor_direction[3]; // M4
    
  //  rt_kprintf("[CTRL] Set targets: %.2f %.2f %.2f %.2f\n",
             //  g_ctrl.v_target[0], g_ctrl.v_target[1],
             //  g_ctrl.v_target[2], g_ctrl.v_target[3]);
   // rt_kprintf("[CTRL] Original targets: %.2f %.2f %.2f %.2f\n", v1, v2, v3, v4);
    rt_mutex_release(g_ctrl.lock);
    return RT_EOK;
}

/* ======================================================================
 * 控制主循环：读取编码器 → PID 计算 → 输出 PWM
 * ====================================================================== */
static void motion_update_control(void)
{
    float w1,w2,w3,w4;
    RT_UNUSED(w1);
    RT_UNUSED(w2);
    RT_UNUSED(w3);
    RT_UNUSED(w4);

    rt_mutex_take(g_ctrl.lock, RT_WAITING_FOREVER);

    /* 开环模式：只读速度日志，不改 PWM（便于 motor_test 逐个测电机） */
    if (g_openloop)
    {
        pulse_get_wheel_speeds(
            &g_ctrl.v_current[0],
            &g_ctrl.v_current[1],
            &g_ctrl.v_current[2],
            &g_ctrl.v_current[3]
        );
        rt_mutex_release(g_ctrl.lock);
        return;
    }

    // 1. 获取当前速度（cm/s）
    pulse_get_wheel_speeds(
        &g_ctrl.v_current[0],
        &g_ctrl.v_current[1],
        &g_ctrl.v_current[2],
        &g_ctrl.v_current[3]
    );
    
   // rt_kprintf("[CTRL] Current speeds: %.2f %.2f %.2f %.2f\n",
    //           g_ctrl.v_current[0], g_ctrl.v_current[1],
     //          g_ctrl.v_current[2], g_ctrl.v_current[3]);

    // 2. 独立 PID 控制（默认模式）
    float pwm[4] = {0};
    for (int i = 0; i < 4; i++) {
        pwm[i] = PID_Compute(&g_ctrl.pid[i], g_ctrl.v_target[i], g_ctrl.v_current[i]);
    }
    
   // rt_kprintf("[CTRL] PWM outputs: %.2f %.2f %.2f %.2f\n",
          //     pwm[0], pwm[1], pwm[2], pwm[3]);

    rt_mutex_release(g_ctrl.lock);

    // 3. 输出到电机（motor_output 内部处理 ID 映射）
    for (int i = 0; i < 4; i++) {
        motor_output(i + 1, pwm[i]); // ID: 1~4
    }
}

/* ======================================================================
 * 控制线程（10ms 周期）
 * ====================================================================== */
static void motion_thread(void *parameter)
{
    RT_UNUSED(parameter);
   // rt_kprintf("[CTRL] Motion control thread started\n");
    while (1) {
        motion_update_control();
        rt_thread_mdelay(10);
    }
}

/* ======================================================================
 * 获取当前轮速（用于调试或上层规划）
 * ====================================================================== */
rt_err_t motion_get_current_speeds(float *v1, float *v2, float *v3, float *v4)
{
    if (!v1 || !v2 || !v3 || !v4) return -RT_ERROR;

    rt_mutex_take(g_ctrl.lock, RT_WAITING_FOREVER);
    *v1 = g_ctrl.v_current[0];
    *v2 = g_ctrl.v_current[1];
    *v3 = g_ctrl.v_current[2];
    *v4 = g_ctrl.v_current[3];
    rt_mutex_release(g_ctrl.lock);
    return RT_EOK;
}

/* ======================================================================
 * 运行时设置某一轮 PID 参数（用于在线调参），并清零积分/微分历史
 * ====================================================================== */
rt_err_t motion_set_pid(int idx, float kp, float ki, float kd)
{
    if (idx < 0 || idx > 3) return -RT_ERROR;

    rt_mutex_take(g_ctrl.lock, RT_WAITING_FOREVER);
    g_ctrl.pid[idx].kp = kp;
    g_ctrl.pid[idx].ki = ki;
    g_ctrl.pid[idx].kd = kd;
    g_ctrl.pid[idx].integral = 0.0f;
    g_ctrl.pid[idx].prev_err = 0.0f;
    rt_mutex_release(g_ctrl.lock);
    return RT_EOK;
}

rt_err_t motion_get_pid(int idx, float *kp, float *ki, float *kd)
{
    if (idx < 0 || idx > 3 || !kp || !ki || !kd) return -RT_ERROR;

    rt_mutex_take(g_ctrl.lock, RT_WAITING_FOREVER);
    *kp = g_ctrl.pid[idx].kp;
    *ki = g_ctrl.pid[idx].ki;
    *kd = g_ctrl.pid[idx].kd;
    rt_mutex_release(g_ctrl.lock);
    return RT_EOK;
}

/* ======================================================================
 * 初始化：电机、编码器、PID、线程
 * ====================================================================== */
rt_err_t motion_ctrl_init(void)
{
   // rt_kprintf("[CTRL] Initializing motion control system\n");
    memset(&g_ctrl, 0, sizeof(g_ctrl));

    g_ctrl.lock = rt_mutex_create("ctrl_lock", RT_IPC_FLAG_FIFO);
    if (g_ctrl.lock == RT_NULL) {
       // rt_kprintf("[ERR] Failed to create control mutex\n");
        return -RT_ERROR;
    }

    // 初始化底层硬件
    init_all_motors();
    if (init_encoders() != RT_EOK) {
      //  rt_kprintf("[ERR] Encoder initialization failed\n");
    }

    // 初始化四轮 PID
    PID_Init(&g_ctrl.pid[0], KP_W1, KI_W1, KD_W1, -100.0f, 100.0f);
    PID_Init(&g_ctrl.pid[1], KP_W2, KI_W2, KD_W2, -100.0f, 100.0f);
    PID_Init(&g_ctrl.pid[2], KP_W3, KI_W3, KD_W3, -100.0f, 100.0f);
    PID_Init(&g_ctrl.pid[3], KP_W4, KI_W4, KD_W4, -100.0f, 100.0f);

    // 启动控制线程
    rt_thread_t tid = rt_thread_create("motion", motion_thread, RT_NULL, 4096, 15, 10);
    if (tid) {
        rt_thread_startup(tid);
       // rt_kprintf("[SYS] Motion control thread started\n");
    } else {
      //  rt_kprintf("[ERR] Failed to create motion thread\n");
        return -RT_ERROR;
    }
    //临时测试：上电直接前进
    // g_vtx = 35.0f;
    // g_vty = 0.0f;
    // g_omega = 0.0f;

    //麦轮直行测试
    /*
    float w1,w2,w3,w4;
    float vtx = 15.0f;
    float vty = 0.0f;
    float omega = 0.0f;
    mecanum_calc(vtx, vty, omega, &w1,&w2,&w3,&w4);
    motion_request_wheels(w1,w2,w3,w4);
    */
    return RT_EOK;
}
//麦轮计算函数
//输入: vtx/vty (cm/s, vtx前进, vty左移), omega (rad/s, 逆时针为正)
//输出: 四轮线速度 (cm/s), 顺序 FL, RL, FR, RR
void mecanum_calc(float vtx, float vty, float omega, float *w1,float *w2,float *w3,float *w4)
{
    /* (轴距/2 + 轮距/2) = (8.0cm + 9.8cm) */
    float ab = 17.8f;
    *w1 = vtx - vty - omega * ab;   /* FL */
    *w2 = vtx + vty - omega * ab;   /* RL */
    *w3 = vtx + vty + omega * ab;   /* FR */
    *w4 = vtx - vty + omega * ab;   /* RR */
}

void motion_dbg_motor(void)
{
    rt_kprintf("=== Motor Debug ===\n");
    for (int i = 0; i < 4; i++) {
        float pwm = g_ctrl.pid[i].kp * (g_ctrl.v_target[i] - g_ctrl.v_current[i])
                    + g_ctrl.pid[i].ki * g_ctrl.pid[i].integral
                    + g_ctrl.pid[i].kd * (g_ctrl.v_target[i] - g_ctrl.v_current[i] - g_ctrl.pid[i].prev_err);
        rt_kprintf("M%d: target=%.2f curr=%.2f pwm=%.2f int=%.2f prev_err=%.2f\n",
                   i + 1, g_ctrl.v_target[i], g_ctrl.v_current[i], pwm,
                   g_ctrl.pid[i].integral, g_ctrl.pid[i].prev_err);
    }
}

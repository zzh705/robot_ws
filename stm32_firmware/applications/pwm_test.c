#include <rtthread.h>
#include <rtdevice.h>
#include <math.h>
#include "pwm_test.h"

#ifndef MAX_MOTOR_COUNT
#define MAX_MOTOR_COUNT 4
#endif

/* PWM 参数 */
#define PWM_PERIOD_NS        (50000U)      /* 20us → 50kHz */
#undef MIN_EFFECTIVE_PWM
#define MIN_EFFECTIVE_PWM    (0.0f)        /* 关死区，确保微小 PWM 也能下发 */
#define PWM_UPDATE_EPSILON   (0.05f)       /* 降低更新阈值提高精度 */

/* 频率相关定义 */
#define DEFAULT_PWM_FREQ     (20000U)      /* 默认PWM频率 20kHz */
#define PWM_FREQ_MIN         (1000U)       /* 最小频率 1kHz */
#define PWM_FREQ_MAX         (50000U)      /* 最大频率 50kHz */

typedef struct
{
    struct rt_device_pwm *pwm_forward;
    rt_uint32_t ch_forward;
    rt_uint32_t period_forward;  /* 正转通道周期(ns) */
    
    struct rt_device_pwm *pwm_backward;
    rt_uint32_t ch_backward;
    rt_uint32_t period_backward; /* 反转通道周期(ns) */
    
    float last_pwm;
    rt_uint32_t frequency;       /* 当前PWM频率（保留用于兼容性） */
} Motor_t;

/* 电机数组：id 1~4 → index 0~3 */
static Motor_t motors[MAX_MOTOR_COUNT] = {0};
static int motors_initialized = 0;


/* 内部辅助函数：安全设置 PWM 脉冲宽度
 * @param m: 电机结构体指针，指向要控制的电机
 * @param forward_pulse: 正转通道的脉冲宽度（纳秒）
 * @param backward_pulse: 反转通道的脉冲宽度（纳秒）
 * 
 * 功能说明：
 * - 安全检查电机指针有效性
 * - 根据当前电机频率计算PWM周期
 * - 分别设置正转和反转通道的PWM输出
 * - 提供错误日志输出
 */
static void _set_motor_pwm(Motor_t *m, rt_uint32_t forward_pulse, rt_uint32_t backward_pulse)
{
    /* 参数有效性检查：防止空指针访问 */
    if (!m) return;

    /* 设置正转通道PWM（如果存在） */
    if (m->pwm_forward)
    {
        /* 调用RT-Thread PWM API设置脉冲参数
         * 参数：设备指针、通道号、周期(ns)、脉冲宽度(ns)
         */
        rt_err_t err = rt_pwm_set(m->pwm_forward, m->ch_forward, m->period_forward, forward_pulse);
        if (err != RT_EOK)
           rt_kprintf("[MOTOR] PWM set failed on forward channel\n");
    }

    /* 设置反转通道PWM（如果存在） */
    if (m->pwm_backward)
    {
        /* 调用RT-Thread PWM API设置脉冲参数
         * 参数：设备指针、通道号、周期(ns)、脉冲宽度(ns)
         */
        rt_err_t err = rt_pwm_set(m->pwm_backward, m->ch_backward, m->period_backward, backward_pulse);
        if (err != RT_EOK)
          rt_kprintf("[MOTOR] PWM set failed on backward channel\n");
    }
}

/* 设置电机PWM频率 */
rt_err_t motor_set_frequency(int id, rt_uint32_t frequency_hz)
{
    if (id < 1 || id > MAX_MOTOR_COUNT)
    {
       // rt_kprintf("[MOTOR] Invalid motor ID: %d\n", id);
        return -RT_ERROR;
    }

    if (frequency_hz < PWM_FREQ_MIN || frequency_hz > PWM_FREQ_MAX)
    {
       // rt_kprintf("[MOTOR] Frequency out of range (%d-%d Hz): %d\n",
                  // PWM_FREQ_MIN, PWM_FREQ_MAX, frequency_hz);
        return -RT_ERROR;
    }

    Motor_t *m = &motors[id - 1];
    m->frequency = frequency_hz;

   // rt_kprintf("[MOTOR] Set M%d frequency to %d Hz\n", id, frequency_hz);
    return RT_EOK;
}

/* 获取电机当前PWM频率 */
rt_uint32_t motor_get_frequency(int id)
{
    if (id < 1 || id > MAX_MOTOR_COUNT)
    {
       // rt_kprintf("[MOTOR] Invalid motor ID: %d\n", id);
        return 0;
    }

    return motors[id - 1].frequency;
}

/* 获取电机当前PWM周期(ns) */
rt_uint32_t motor_get_period_ns(int id)
{
    if (id < 1 || id > MAX_MOTOR_COUNT)
    {
       // rt_kprintf("[MOTOR] Invalid motor ID: %d\n", id);
        return 0;
    }

    Motor_t *m = &motors[id - 1];
    return 1000000000U / m->frequency;
}

/* 前向声明 */
static void motor_init(Motor_t *m,
                       const char *fw_name, rt_uint32_t fw_ch, rt_uint32_t fw_period,
                       const char *bw_name, rt_uint32_t bw_ch, rt_uint32_t bw_period);

/* 初始化所有电机 */
void init_all_motors(void)
{
    if (motors_initialized) return;

    /* 根据实际硬件配置初始化电机，注意通道映射 */
    rt_kprintf("[MOTOR] Initializing motors...\n");
    motor_init(&motors[0], "pwm1", 3, PWM_PERIOD_NS, "pwm1", 4, PWM_PERIOD_NS); /* M1: 左前 */
    motor_init(&motors[1], "pwm1", 2, PWM_PERIOD_NS, "pwm1", 1, PWM_PERIOD_NS); /* M2: 左后 */
    motor_init(&motors[2], "pwm9", 2, PWM_PERIOD_NS, "pwm9", 1, PWM_PERIOD_NS); /* M3: 右前 */
    motor_init(&motors[3], "pwm12", 1, PWM_PERIOD_NS, "pwm12", 2, PWM_PERIOD_NS); /* M4: 右后 */

    motors_initialized = 1;
    rt_kprintf("[SYS] Motors initialized: M1/M2=20kHz, M3/M4=10kHz\n");
    //rt_kprintf("[SYS] Motor gains: [%.2f, %.2f, %.2f, %.2f]\n", 
              //motor_gain[0], motor_gain[1], motor_gain[2], motor_gain[3]);
}

/* 初始化单个电机 */
static void motor_init(Motor_t *m,
                       const char *fw_name, rt_uint32_t fw_ch, rt_uint32_t fw_period,
                       const char *bw_name, rt_uint32_t bw_ch, rt_uint32_t bw_period)
{
    RT_ASSERT(m != RT_NULL);

   // rt_kprintf("[MOTOR] Initializing motor: %s/%d and %s/%d\n", fw_name, fw_ch, bw_name, bw_ch);
    
    m->pwm_forward  = (struct rt_device_pwm *)rt_device_find(fw_name);
    m->ch_forward   = fw_ch;
    m->period_forward = fw_period;
    
    m->pwm_backward = (struct rt_device_pwm *)rt_device_find(bw_name);
    m->ch_backward  = bw_ch;
    m->period_backward = bw_period;
    
    m->last_pwm     = 0.0f;
    m->frequency    = DEFAULT_PWM_FREQ;  /* 设置默认频率（保留用于兼容性） */

    if (!m->pwm_forward || !m->pwm_backward)
    {
       // rt_kprintf("[MOTOR] Error: PWM device not found for %s/%s\n", fw_name, bw_name);
        return;
    }

    /* 初始化为 0 并启用 */
    rt_pwm_set(m->pwm_forward,  m->ch_forward,  m->period_forward,  0);
    rt_pwm_set(m->pwm_backward, m->ch_backward, m->period_backward, 0);
    rt_pwm_enable(m->pwm_forward,  m->ch_forward);
    rt_pwm_enable(m->pwm_backward, m->ch_backward);
    
    rt_kprintf("[MOTOR] Successfully initialized motor channels\n");
}

/* 输出 PWM 到指定电机（id: 1~4） */
void motor_output(int id, float pwm_percent)
{
    if (id < 1 || id > MAX_MOTOR_COUNT)
    {
       // rt_kprintf("[MOTOR] Invalid motor ID: %d\n", id);
        return;
    }

    if (pwm_percent > 60.0f) pwm_percent = 60.0f;
    if (pwm_percent < -60.0f) pwm_percent = -60.0f;

    Motor_t *m = &motors[id - 1];
    
    //rt_kprintf("[MOTOR] M%d: PWM=%d\n", id, (int)(pwm_percent * 1000));
    // rt_kprintf("[MOTOR] M%d: PWM=%.2f%%\n", id, pwm_percent);

    // 计算绝对值和方向
    float abs_pwm = fabsf(pwm_percent);

    // 如果PWM值太小，直接停止电机
    if (abs_pwm < MIN_EFFECTIVE_PWM)
    {
       // rt_kprintf("[MOTOR] Motor %d below threshold (%.2f < %.2f)\n", id, abs_pwm, MIN_EFFECTIVE_PWM);
        // 如果与上次输出差异较大才更新
        if (fabsf(m->last_pwm) > PWM_UPDATE_EPSILON)
        {
            _set_motor_pwm(m, 0, 0);
            m->last_pwm = 0.0f;
        }
        return;
    }

    // 计算脉冲宽度（纳秒）
    rt_uint32_t period_ns = motor_get_period_ns(id);
    rt_uint32_t pulse_ns = (rt_uint32_t)((abs_pwm / 100.0f) * period_ns);
    if (pulse_ns > period_ns) pulse_ns = period_ns;

   // rt_kprintf("[MOTOR] Motor %d: pulse=%d ns, period=%d ns\n", id, pulse_ns, period_ns);

    // 差动PWM模式（与官方 ax_motor 一致）：
    // 一路满载、另一路互补，两个通道都有波形，靠差值驱动电机
    if (pwm_percent >= 0)
    {
        // 正转：forward 通道满载，backward 通道互补
        _set_motor_pwm(m, period_ns, period_ns - pulse_ns);
    }
    else
    {
        // 反转：backward 通道满载，forward 通道互补
        _set_motor_pwm(m, period_ns - pulse_ns, period_ns);
    }

    m->last_pwm = pwm_percent;
}

#ifndef __PWM_TEST_H__
#define __PWM_TEST_H__

#include <rtthread.h>
#include <rtdevice.h>

#ifdef __cplusplus
extern "C" {
#endif

/* PWM 参数 */
#define PWM_PERIOD_NS        (50000U)      /* 20us → 50kHz */
#define MIN_EFFECTIVE_PWM    (1.0f)        /* 降低死区阈值至2% */
#define PWM_UPDATE_EPSILON   (0.05f)       /* 降低更新阈值提高精度 */

/* 频率相关定义 */
#define DEFAULT_PWM_FREQ     (20000U)      /* 默认PWM频率 20kHz */
#define PWM_FREQ_MIN         (1000U)       /* 最小频率 1kHz */
#define PWM_FREQ_MAX         (50000U)      /* 最大频率 50kHz */
/* 电机数量（M1 左前，M2 左后，M3 右前，M4 右后） */
#define MAX_MOTOR_COUNT 4

/* 初始化所有电机 PWM 通道 */
void init_all_motors(void);

/*
 * 输出 PWM 给指定电机
 * id: 1~4
 * pwm_percent: -100.0f ~ 100.0f
 * 正数：前进方向，负数：后退方向（方向会再经过 motor_dir 统一）
 */
void motor_output(int id, float pwm_percent);

/* 设置电机PWM频率 */
rt_err_t motor_set_frequency(int id, rt_uint32_t frequency_hz);

/* 获取电机当前PWM频率 */
rt_uint32_t motor_get_frequency(int id);

/* 获取电机当前PWM周期(ns) */
rt_uint32_t motor_get_period_ns(int id);
/* PWM 参数 */


#ifdef __cplusplus
}
#endif

#endif /* __PWM_TEST_H__ */

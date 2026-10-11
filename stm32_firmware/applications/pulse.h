#ifndef __PULSE_H__
#define __PULSE_H__

#include <rtthread.h>
#include <rtdevice.h>

/* ===== 修正后的参数 ===== */
#define WHEEL_DIAMETER_CM   9.7f      // 轮子直径 9.7 cm (实测)
#define GEAR_RATIO          30.0f     // 减速比 1:30
#define ENCODER_LINES       1024.0f   // 编码器 1024 线（四倍频后 4096/电机圈，×30 减速比 = 122880/轮圈，实测标定）

rt_err_t init_encoders(void);
void pulse_get_wheel_speeds(float *v1, float *v2, float *v3, float *v4);
void pulse_get_counts(int counts[4]);
/* 读取四轮原始累计脉冲（不做滑动滤波），用于向上位机回传 */
void pulse_get_raw_counts(rt_int32_t counts[4]);

/* 清零四轮累计脉冲（含 over/underflow 计数），用于编码器标定 */
void pulse_clear_counts(void);

#endif

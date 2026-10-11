#ifndef __MOTION_CTRL_H__
#define __MOTION_CTRL_H__

#include <rtthread.h>

typedef enum {
    CTRL_MODE_INDEPENDENT = 0,
    CTRL_MODE_UNIFIED
} ctrl_mode_t;

rt_err_t motion_ctrl_init(void);
rt_err_t motion_set_openloop(rt_bool_t enable);
rt_err_t motion_set_control_mode(int mode);
rt_err_t motion_request_wheels(float v1, float v2, float v3, float v4);
rt_err_t motion_set_motor_direction(float dir1, float dir2, float dir3, float dir4);
rt_err_t motion_get_motor_direction(float d[4]);
rt_err_t motion_get_current_speeds(float *v1, float *v2, float *v3, float *v4);
rt_err_t motion_set_pid(int idx, float kp, float ki, float kd);
rt_err_t motion_get_pid(int idx, float *kp, float *ki, float *kd);
void mecanum_calc(float vtx, float vty, float omega, float *w1,float *w2,float *w3,float *w4);
void motion_dbg_motor(void);
#endif

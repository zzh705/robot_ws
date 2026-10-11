#include <rtthread.h>
#include <rtdevice.h>
#include "pulse.h"
#include <math.h>

#define RT_PI 3.1415926f

/* 编码器数据消抖配置 */
#define FILTER_WINDOW_SIZE 3 // 滑动窗口大小（越大滤波效果越好，但响应越慢）

// 添加最大速度限制，防止异常值
#define MAX_WHEEL_SPEED 100.0f // cm/s

static rt_device_t pulse_dev[4] = {RT_NULL};
static int last_counts[4] = {0};
static float last_speed[4] = {0};
static rt_tick_t last_tick = 0;

/* 编码器方向校正系数：使"电机正输出 -> 编码器正反馈"，逐轮标定
 * 顺序: FL, RL, FR, RR。实测 FL/RL 原始计数与电机反向(取-1)，
 * FR/RR 与电机同向(取+1)，否则 PID 正反馈导致飞车 */
static int wheel_dir[4] = {-1, -1, +1, +1};

int globalv1 = 0;
int globalv2 = 0;
int globalv3 = 0;
int globalv4 = 0;



/* 滑动窗口缓冲区，用于编码器计数消抖 */
static int filter_buffer[4][FILTER_WINDOW_SIZE] = {0};
static int filter_buffer_index[4] = {0};
static rt_bool_t filter_initialized[4] = {RT_FALSE};

/* 编码器设备名与轮子的对应关系
 * 注意：这里需要根据实际硬件连接进行调整
 * 顺序为：W1(左前), W2(左后), W3(右前), W4(右后)
 * 与电机的对应关系保持一致：M1(左前), M2(左后), M3(右前), M4(右后)
 */
static const char *pulse_name[4] = {"pulse3","pulse2","pulse5","pulse4"};

/* 打开所有编码器设备 */
rt_err_t init_encoders(void)
{
   // rt_kprintf("[ENC] Initializing encoders...\n");
    for (int i = 0; i < 4; i++)
    {
        pulse_dev[i] = rt_device_find(pulse_name[i]);
        if (!pulse_dev[i])
        {
           // rt_kprintf("[ENC] device %s NOT found\n", pulse_name[i]);
            return -RT_ERROR;
        }
        rt_err_t result = rt_device_open(pulse_dev[i], RT_DEVICE_OFLAG_RDWR);
        if (result != RT_EOK) {
           // rt_kprintf("[ENC] Failed to open device %s, error: %d\n", pulse_name[i], result);
            return -RT_ERROR;
        }
       // rt_kprintf("[ENC] %s ok\n", pulse_name[i]);
    }
    // 初始化last_counts数组，读取当前编码器值
    int initial_counts[4];
    for (int i = 0; i < 4; i++)
    {
        rt_size_t result = rt_device_read(pulse_dev[i], 0, &initial_counts[i], sizeof(int));
        if (result == 1) {
            last_counts[i] = initial_counts[i];
            last_speed[i] = 0.0f; // 初始化速度为0
        } else {
            //rt_kprintf("[ENC] Failed to read initial encoder %d, result: %d\n", i, result);
            last_counts[i] = 0;
            last_speed[i] = 0.0f;
        }
    }
    
    last_tick = rt_tick_get();
   // rt_kprintf("[ENC] Encoders initialized successfully\n");
    return RT_EOK;
}

/* 滑动平均滤波函数 */
static int filter_encoder_data(int wheel_id, int new_count)
{
    int sum = 0;
    int i;
    
    /* 将新数据存入滑动窗口缓冲区 */
    filter_buffer[wheel_id][filter_buffer_index[wheel_id]] = new_count;
    filter_buffer_index[wheel_id] = (filter_buffer_index[wheel_id] + 1) % FILTER_WINDOW_SIZE;
    
    /* 如果缓冲区未初始化，则初始化所有元素为当前值 */
    if (!filter_initialized[wheel_id])
    {
        for (i = 0; i < FILTER_WINDOW_SIZE; i++)
        {
            filter_buffer[wheel_id][i] = new_count;
        }
        filter_initialized[wheel_id] = RT_TRUE;
    }
    
    /* 计算滑动窗口的平均值 */
    for (i = 0; i < FILTER_WINDOW_SIZE; i++)
    {
        sum += filter_buffer[wheel_id][i];
    }
    
    return sum / FILTER_WINDOW_SIZE;
}

/* 每个编码器的计数（带消抖） */
void pulse_get_counts(int counts[4])
{
    int raw_counts[4];
    
    /* 读取原始编码器数据 */
    for (int i = 0; i < 4; i++)
    {
        rt_size_t result = rt_device_read(pulse_dev[i], 0, &raw_counts[i], sizeof(int));
        if (result == 1) {
            // 增加数据有效性检查，防止异常值
            
        } else {
           // rt_kprintf("[ENC] Failed to read encoder %d, result: %d\n", i, result);
            raw_counts[i] = last_counts[i]; // 使用上次的值
        }
    }
    
    /* 对原始数据进行消抖处理并应用方向校正 */
    for (int i = 0; i < 4; i++)
    {
        counts[i] = filter_encoder_data(i, raw_counts[i]) * wheel_dir[i];
    }
}

/* 上位机上报用的方向符号：与电机指令方向(g_motor_direction)配对，
 * 统一"前进 -> 正计数"，供上位机里程计使用。顺序 FL,RL,FR,RR */
static int encoder_report_dir[4] = {-1, -1, -1, -1};

/* 读取四轮原始累计脉冲（不做滑动滤波），供上位机里程计使用 */
void pulse_get_raw_counts(rt_int32_t counts[4])
{
    for (int i = 0; i < 4; i++)
    {
        int raw = last_counts[i];
        if (rt_device_read(pulse_dev[i], 0, &raw, sizeof(int)) == 1)
        {
            counts[i] = (rt_int32_t)raw * encoder_report_dir[i];
        }
        else
        {
            counts[i] = (rt_int32_t)last_counts[i] * encoder_report_dir[i];
        }
    }
}

/* 清零四轮累计脉冲（含 over/underflow 计数），用于编码器标定 */
void pulse_clear_counts(void)
{
    for (int i = 0; i < 4; i++)
    {
        if (pulse_dev[i] != RT_NULL)
        {
            rt_device_control(pulse_dev[i], PULSE_ENCODER_CMD_CLEAR_COUNT, RT_NULL);
        }
    }
}

/* 计算 4 轮速度（cm/s） */
void pulse_get_wheel_speeds(float *v1, float *v2, float *v3, float *v4)
{
    int curr[4];
    pulse_get_counts(curr);

    rt_tick_t now = rt_tick_get();
    // 防止除零错误和时间倒流
    rt_tick_t delta_tick = now - last_tick;
    if (delta_tick == 0) {
        // 时间间隔为0，返回上次的速度值
        *v1 = last_speed[0];
        *v2 = last_speed[1];
        *v3 = last_speed[2];
        *v4 = last_speed[3];
        return;
    }
    
    float dt = (float)delta_tick / RT_TICK_PER_SECOND;   // 转为秒

    // 检查时间间隔是否合理（防止异常值）
    if (dt <= 0 || dt > 0.5f) {  // 超过500ms认为异常
       // rt_kprintf("[ENC] Abnormal time interval: %.6f s\n", dt);
        *v1 = last_speed[0];
        *v2 = last_speed[1];
        *v3 = last_speed[2];
        *v4 = last_speed[3];
        last_tick = now;  // 更新时间戳
        return;
    }

    float perimeter = RT_PI * WHEEL_DIAMETER_CM;
    float ppr = ENCODER_LINES * GEAR_RATIO * 4;

    float new_speeds[4];
    for (int i = 0; i < 4; i++)
    {
        int diff = curr[i] - last_counts[i];
        last_counts[i] = curr[i];

        float rev = (float)diff / ppr;
        float dist = rev * perimeter;
        new_speeds[i] = dist / dt;
        
        // 应用方向校正

        // 限制最大速度，防止异常值
        if (new_speeds[i] > MAX_WHEEL_SPEED) {
            new_speeds[i] = MAX_WHEEL_SPEED;
          //  rt_kprintf("[ENC] Wheel %d speed limited to max: %.2f cm/s\n", i, MAX_WHEEL_SPEED);
        } else if (new_speeds[i] < -MAX_WHEEL_SPEED) {
            new_speeds[i] = -MAX_WHEEL_SPEED;
           // rt_kprintf("[ENC] Wheel %d speed limited to min: %.2f cm/s\n", i, -MAX_WHEEL_SPEED);
        }
        
        // 如果速度变化过大，可能是噪声，使用上次的值
        if (fabsf(new_speeds[i] - last_speed[i]) > 50.0f && fabsf(last_speed[i]) > 1.0f) {
            //rt_kprintf("[ENC] Wheel %d speed jump detected: %.2f -> %.2f\n",
                   //   i, last_speed[i], new_speeds[i]);
            new_speeds[i] = last_speed[i]; // 使用上次的速度值
        }
    }

    last_tick = now;

    *v1 = new_speeds[0];
    *v2 = new_speeds[1];
    *v3 = new_speeds[2];
    *v4 = new_speeds[3];
    
    // 更新last_speed数组
    last_speed[0] = new_speeds[0];
    last_speed[1] = new_speeds[1];
    last_speed[2] = new_speeds[2];
    last_speed[3] = new_speeds[3];
    
    // 更新全局速度变量
    globalv1 = (int)(new_speeds[0]*1000);
    globalv2 = (int)(new_speeds[1]*1000);
    globalv3 = (int)(new_speeds[2]*1000);
    globalv4 = (int)(new_speeds[3]*1000);
    
    // 输出调试信息
   // rt_kprintf("[ENC] Speeds: %d %d %d %d cm/s\n", globalv1, globalv2, globalv3, globalv4);
}

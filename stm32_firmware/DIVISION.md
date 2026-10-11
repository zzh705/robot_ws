# 麦克纳姆轮机器人 - 开发模块分工

> 分工日期：2026-09-14
> 分工比例：A（你）负责 2/3，B（另一位）负责 1/3

---

## 模块 A：运动控制核心 + 通讯/命令（你负责）

### A1. 运动控制核心（已完成主体，待闭环验证）

| 文件 | 说明 | 状态 |
|---|---|---|
| `applications/motion_ctrl.c/h` | 麦轮逆运动学、四轮 PID、10ms 控制线程、`g_vtx` 直行测试 | 已跑通，待调参 |
| `applications/pwm_test.c/h` | 电机差动 PWM 输出（单边→差动已改，占空比 15→35） | 已改好 |
| `applications/pulse.c/h` | 编码器测速、cm/s 换算 | 待验证计数 |
| `drivers/` 中 TIM/PWM/编码器相关 | 底层驱动、TIM1/9/12 引脚复用 | 已确认正确 |

待办：
- 验证四个编码器计数是否能读到（昨天忙时读到 TIM2/3/4/5 计数仍为 0）
- PID 闭环调参、方向校正实测
- `motion_ctrl_init()` 直行测试已在 main.c:141 启用

### A2. 通讯/命令/主流程（残留串口乱码问题）

| 文件 | 说明 | 状态 |
|---|---|---|
| `applications/main.c` | 主程序：UART3 接收 + 命令消息队列 + 电机初始化入口 | 未解决乱码 |
| `applications/cmd_ctrl.c` | Finsh/MSH 命令：motor_test、motor_test_all、get_speeds、move_spd、strafe_spd、mstop | 可用 |

待办：
- **修复 UART3 (115200) 串口乱码** —— 昨天已暂停，根源疑似波特率不匹配（HEX 无规律乱码），下一步应从时钟配置（RCC_CFGR / PLLCFGR / USART3_BRR）排查
- 上位机协议对接

---

## 模块 B：感知/扩展模块（B 负责）

### B1. MPU6050 姿态传感器

| 文件 | 说明 | 状态 |
|---|---|---|
| `applications/MPU6050.c/h` | 姿态传感器：I2C 读写、量程配置、`MPU6050_Init`/`ReadSensors` | 代码通常已写好但**未在 main.c 接入** |
| `drivers/include/drv_soft_i2c.h` | 软件 I2C（`i2c1`/`i2c2` 总线） | 依赖项 |

待办（按顺序）：
1. **确认 I2C 总线已注册**：检查 `drivers/board.h` 中 `BSP_USING_I2C1` 是否打开；MPU6050 用 `"i2c1"`。
2. **接线确认**：明确 MPU6050 SDA/SCL 接到那两条 GPIO，对照 `drv_soft_i2c.h` 引脚定义。
3. **在 main() 中接入初始化**：调用 `MPU6050_Init("i2c1")` 并校验返回值；目前已有一个 `mpu6050_test_thread` 测试线程（`INIT_APP_EXPORT(mpu6050_auto_init)` 自动启动），如果默认已注册，观察串口是否打印 `WHO_AM_I check passed`（应读到 0x68）。
4. **数据读取**：`MPU6050_ReadSensors()` 输出加速度（g）和角速度（°/s）。
5. **联调**：与模块 A 的 `globalv1..4` 速度变量配合（MPU6050.c 已有 `extern int globalv1` 等），如需数据回传走 UART3，注意串口乱码问题属 A2，测试时可先只看串口终端 kprintf。

> 重要：MPU6050 的 I2C 若读到全 0 或超时，优先查接线 + `WHO_AM_I`（0x68）而非改代码。

### B2. 其他未接入外设驱动（可选）

| 文件 | 说明 | 状态 |
|---|---|---|
| `drivers/` 下 ADC/其他外设 | 按需接入 | 未接入 |

---

## 开始方式（给 B 的新人）

1. 打开工程 `D:\Stm32_F407_3_27_improve`（RT-Thread Studio 工程）。
2. 先读 `applications/MPU6050.c` 和 `applications/MPU6050.h`，理解 I2C 读写、初始化和测试线程。
3. 查看 `drivers/include/drv_soft_i2c.h` 和 `drivers/board.h`，确认 `BSP_USING_I2C1` 已开、GPIO 引脚定义。
4. 接线 MPU6050 到板子的 I2C1 引脚，通电后在串口终端观察 `[MPU6050]` 打印：
   - 若看到 `WHO_AM_I check passed: 0x68` → 初始化成功；
   - 若失败 → 检查接线/引脚/设备地址。
5. 用 J-Link/ST-Link（或探针工程原有的下载方式）编译烧录到 STM32F407 板，串口观察数据。
6. 参考：模块 A 已跑通轮子转动（PWM 差动模式），MPU6050 数据可在终端单独验证，不与轮子测试冲突。

---

## 联调约定（避免两人互相阻塞）

- **共享文件：都不改** `applications/main.c` 的初始化顺序（A2 在处理串口问题时可能改动 main.c 的 UART 部分，B 不要同时动 main.c）。
- **串口 UART3** 被 A2 与 B 都用到：B 测试 MPU6050 回传时需与 A 约定波特率/格式，避免互相覆盖。
- **分支管理**：建议各自建分支，merge 前通知对方。
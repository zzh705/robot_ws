/*
 * Copyright (c) 2006-2021, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2025-09-30     lenovo       the first version
 */
#ifndef RT_THREAD_COMPONENTS_FAL_INC_FAL_CFG_H_
#define RT_THREAD_COMPONENTS_FAL_INC_FAL_CFG_H_



#endif /* RT_THREAD_COMPONENTS_FAL_INC_FAL_CFG_H_ */


#ifndef __FAL_CFG_H__
#define __FAL_CFG_H__

#include <rtthread.h>
#include <fal.h>

/* 启用分区表 */
#define FAL_PART_HAS_TABLE_CFG

/* flash 设备表定义 */
#define FAL_FLASH_DEV_TABLE                                                  \
{                                                                            \
    &onchip_flash,  /* 对应 BSP 中的 onchip_flash 设备 */                   \
}

/* 分区表 */
#define FAL_PART_TABLE                                                       \
{                                                                            \
    { "bootloader", "onchip_flash", 0x08000000, 64*1024, 0 },               \
    { "app",        "onchip_flash", 0x08010000, 512*1024, 0 },              \
    { "easyflash",  "onchip_flash", 0x08090000, 16*1024, 0 },               \
    { "log",        "onchip_flash", 0x08094000, 16*1024, 0 },               \
}

#endif /* __FAL_CFG_H__ */


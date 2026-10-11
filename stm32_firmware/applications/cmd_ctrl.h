#ifndef __CMD_CTRL_H__
#define __CMD_CTRL_H__

#include <rtthread.h>

/*
 * cmd_ctrl.c 仅用于注册 FinSH shell 命令，
 * 正常业务代码应直接调用 motion_ctrl.h 中的 API。
 */

#ifdef __cplusplus
extern "C" {
#endif

/* 如需在其它模块直接调用 shell 命令，可在此添加声明，但一般不建议 */

#ifdef __cplusplus
}
#endif

#endif /* __CMD_CTRL_H__ */

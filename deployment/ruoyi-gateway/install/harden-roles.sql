-- RUOYI-AUTH-GATEWAY-001 Phase 6 生产加固
-- 清空内置"普通角色"(role_id=2) 的菜单绑定：普通用户登录若依后只看到首页，
-- 不再暴露系统管理/系统监控/系统工具菜单及其接口权限。
-- 业务能力入口是 /agent-api/ 操作台，与若依菜单无关；角色判定只看 roleKey
-- （developer/admin → 开发者控制台，其余 → 普通用户，见契约 §6）。
DELETE FROM sys_role_menu WHERE role_id = 2;

-- 以下为基线核对（stock SQL 已是这些值，不必执行）：
--   sys_config.sys.account.captchaEnabled = true     验证码开启（防爆破）
--   sys_config.sys.account.registerUser  = false     不开放注册
-- 登录失败限制由 application.yml 的 user.password.maxRetryCount=5 / lockTime=10 提供。

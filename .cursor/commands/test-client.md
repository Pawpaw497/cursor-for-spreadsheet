# /test-client — 前端单元测试

用户通过 `/test-client` 显式请求时执行。

## 目标

运行 client 侧 Vitest（`npm test` = `vitest run`）。

## 步骤

1. `cd client`
2. 若缺依赖：`npm install`
3. `npm test`

## 约束

- 不启动 Vite dev server，除非测试失败需要用户手动复现 UI。
- 汇报：退出码、失败用例名与首条错误信息。

## 参考

- `client/package.json` scripts；`README.md` § 测试（含 `llm.preview.test.ts`、`llm.fetchAbort.test.ts` 等）

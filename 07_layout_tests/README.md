# 排布系统测试目录

- 标注时间：2026-06-08
- 用途：批量检查组团规则、手工布局和自动推荐布局是否存在问题

## 文件说明

- `run_layout_diagnostics.py`
  批量测试脚本，会自动生成图片、CSV、分析报告和总摘要。

- `outputs/`
  每次运行后输出的测试结果目录。

## 运行方式

```bash
python d:\zhintiweapp\规则系统\07_layout_tests\run_layout_diagnostics.py
```

## 主要输出

- `outputs/summary.md`
  本次批量测试的总摘要。

- `outputs/summary.json`
  结构化测试结果。

- `outputs/<case_name>/layout.png`
  单个案例的布局图。

- `outputs/<case_name>/layout_analysis.csv`
  单个案例的群组边界数据。

- `outputs/<case_name>/layout_analysis_analysis.txt`
  单个案例的重叠与边界分析。

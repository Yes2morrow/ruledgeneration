"""修复所有群组YAML中非法的arrangement单行格式"""
import re
from pathlib import Path

group_dir = Path(r'd:\zhintiweapp\规则系统2\configs\groups')

for filepath in sorted(group_dir.glob('group_*.yaml')):
    text = filepath.read_text(encoding='utf-8')
    original = text
    # 修复 - row: X, col: Y, rotation: Z, mirror: M  ->  - {row: X, col: Y, rotation: Z, mirror: M}
    text = re.sub(
        r'- row: (\d+), col: (\d+), rotation: (\d+), mirror: (\w+)',
        r'- {row: \1, col: \2, rotation: \3, mirror: \4}',
        text
    )
    if text != original:
        filepath.write_text(text, encoding='utf-8')
        print(f"已修复: {filepath.name}")
    else:
        print(f"无需修复: {filepath.name}")

print("\n验证中...")
import yaml
errors = []
for filepath in sorted(group_dir.glob('group_*.yaml')):
    try:
        yaml.safe_load(filepath.read_text(encoding='utf-8'))
        print(f"OK: {filepath.name}")
    except Exception as e:
        errors.append((filepath.name, str(e)))
        print(f"ERROR: {filepath.name} -> {e}")

if errors:
    print(f"\n仍有 {len(errors)} 个文件解析失败")
else:
    print("\n所有群组YAML解析成功!")

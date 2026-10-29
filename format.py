import re

with open("tests/integration/test_roughmix_api.py", "r") as f:
    content = f.read()

# E401 (Multiple imports)
content = re.sub(r'import json, os', 'import json\nimport os', content)
content = re.sub(r'from strata360.edit import roughmix as RM, project as PJ', 'from strata360.edit import project as PJ\nfrom strata360.edit import roughmix as RM', content)
# F401 (Unused imports)
content = re.sub(r'import pytest\n', '', content)
content = re.sub(r'from strata360.server import app\n', '', content)
# E702 (Multiple statements on one line - semicolon)
content = re.sub(r'edit = PJ.load\(folder\); edit\[\'plan\'\] = dict', 'edit = PJ.load(folder)\n    edit[\'plan\'] = dict', content)
# E701 (Multiple statements on one line - colon)
content = re.sub(r'with open\(RM.path_of\(folder\), \'wb\'\) as f: f.write\(b\'x\'\)', 'with open(RM.path_of(folder), \'wb\') as f:\n        f.write(b\'x\')', content)
content = re.sub(r'with open\(os.path.join\(RM.dir_of\(folder\), \'mix.json\'\), \'w\'\) as f: json.dump\(dict\(length_s=8.0, source=\'script\', parts=RM.parts_of\(folder, edit\[\'plan\'\]\)\), f\)', 'with open(os.path.join(RM.dir_of(folder), \'mix.json\'), \'w\') as f:\n        json.dump(dict(length_s=8.0, source=\'script\', parts=RM.parts_of(folder, edit[\'plan\'])), f)', content)
content = re.sub(r'with open\(os.path.join\(RM.dir_of\(folder\), \'mix.log\'\), \'w\'\) as f: f.write\(\'error something broke\'\)', 'with open(os.path.join(RM.dir_of(folder), \'mix.log\'), \'w\') as f:\n        f.write(\'error something broke\')', content)


with open("tests/integration/test_roughmix_api.py", "w") as f:
    f.write(content)

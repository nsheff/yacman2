test yacman

import yacman2 as yacman
ycm = yacman.YAMLConfigManager({"x": 5})
ycm
ycm["x"]
ycm.writable

ycm.__internal
ycm.__internal["write_validate"]

with ycm as _:
	pass


ycm["pathA"] = "~"
ycm["pathA"]

# get raw items
dict(ycm.items())


ycm2 = yacman.YAMLConfigManager(filepath="/home/nsheff/code/yacman2/tests/data/conf.yaml", writable=True)

ycm2.__internal

ycm2.make_readonly()



with yacman.YAMLConfigManager(filepath="/home/nsheff/code/yacman2/tests/data/conf.yaml") as ycm:
	ycm["abc"] = 3

- .write should be a private function (moved to _write)
- writing should only happen in a context manager.


# test pipestat

import pipestat
p = pipestat.PipestatManager(schema_path="/home/nsheff/code/pipestat/tests/data/sample_output_schema.yaml", namespace="test", database_only=False, results_file_path="/home/nsheff/code/pipestat/tests/data/results_file.yaml")

p.data
p.report(record_identifier="sample1", values={"number_of_things": 5})
p.data["test"]["sample1"]



type(p.data)
type(p["_data"])
type(p)

# direct entry doesn't work:
p.data["test"]
p.data["test"]["sample1"]
p.data["test"]["sample1"] = 1
p.data["test"]

# still doesn't work:
ycm = p.data
ycm["test"]["sample1"] = 1
ycm
p.data["test"]

# this works:

d = ycm.to_dict()
d["test"]["sample1"] = 1
p.data["test"]


# is it a problem with yacman alone?
import yacman2
y = yacman2.YAMLConfigManager({})
y.settings
y["test"] = {}
y
y["test"]["sample1"] = "$HOME"
y

y["test"]["sample1"] 
y.exp["test"]["sample1"]

y["test"]["sample1"] = {}
y["test"]["sample1"]["home"] = "$HOME"
y["test"]["sample1"]["home"]
y.x["test"]["sample1"]
y.x
y["test"]["sample1"]["home"]


import os
from tempfile import mkdtemp
from pipestat import PipestatManager
schema_file_path = "/home/nsheff/code/pipestat/tests/data/sample_output_schema.yaml"
tmp_res_file = os.path.join(mkdtemp(), "res.yml")
print(f"Temporary results file: {tmp_res_file}")
assert not os.path.exists(tmp_res_file)
psm = PipestatManager(
    namespace="test",
    results_file_path=tmp_res_file,
    schema_path=schema_file_path,
)
assert os.path.exists(tmp_res_file)
with psm.data as _:
	_.write()

psm.data

psm.report(record_identifier="sample1", values={"number_of_things": 5})
psm.report(record_identifier="sample1", values={"name_of_something": "test"})


del psm.data["test"]["sample1"]["number_of_things"]
psm.remove("sample1", "number_of_things")
psm.data




psm2 =  PipestatManager(
        namespace="new_test",
        results_file_path=tmp_res_file,
        schema_path=schema_file_path,
    )


psm2







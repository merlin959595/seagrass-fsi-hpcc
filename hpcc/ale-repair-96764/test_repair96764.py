#!/usr/bin/env python3
"""Offline fail-closed tests for the 96764 repair harness (no HPCC needed)."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("repair96764",HERE/"repair96764.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

HEADER="""FoamFile
{
    version 2.0;
    format ascii;
    class labelList;
    object owner;
}
"""

class RepairTests(unittest.TestCase):
    def test_ascii_label_list(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"labels"
            p.write_text(HEADER+"3\n(\n1\n7\n3535\n)\n")
            self.assertEqual(m.read_labels(p),[1,7,3535])
            p.write_text(HEADER+"0\n(\n)\n")
            self.assertEqual(m.read_labels(p),[])

    def test_binary_declared_ascii_content(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"labels"
            p.write_text(HEADER.replace("format ascii","format binary")+"1\n(\n3535\n)\n")
            self.assertEqual(m.read_labels(p),[3535])

    def test_field_parse_and_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"field"
            p.write_text("""FoamFile { version 2.0; format ascii; class surfaceScalarField; }
dimensions [0 0 0 0 0 0 0];
internalField nonuniform List<scalar>
3
(
5931.11453589184
6785.157856
8272.74259869362
)
;
boundaryField { bladeInterface { type calculated; value uniform 1; } }
""")
            data,start,end,vals=m.field_values(p)
            self.assertEqual(len(vals),3)
            self.assertAlmostEqual(min(vals),5931.11453589184)
            self.assertTrue(data[:start].endswith(b"("))
            self.assertTrue(data[end:].startswith(b")"))
            p.write_bytes(data.replace(b"8272.74259869362",b"-5"))
            with self.assertRaises(RuntimeError):
                m.field_values(p)

    def test_fail_closed_missing_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            good,why=m.valid_stage(Path(d),144,0.5815)
            self.assertFalse(good)
            self.assertEqual(why,"MISSING_NATIVE_FSI_RESULT")

    def test_not_overwrite_output(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/"f.json"
            m.dump(f,{"status":"first"})
            with self.assertRaises(RuntimeError):
                m.dump(f,{"status":"second"})

if __name__=="__main__":
    unittest.main()

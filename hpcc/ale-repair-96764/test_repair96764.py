#!/usr/bin/env python3
"""Offline fail-closed tests for the 96764 repair harness (no HPCC needed)."""
import importlib.util
from pathlib import Path
import tempfile
import struct
import shutil
from unittest import mock
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



    def test_binary_surface_scalar_field_roundtrip(self):
        # Reproduces an OpenFOAM rank-local constant/motionReferenceDiffusivity
        # declaring format binary, arch LSB;label=32;scalar=64.
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"motionReferenceDiffusivity"
            header=(
                'FoamFile\n{\n version 2.0; format binary;\n'
                ' arch "LSB;label=32;scalar=64";\n'
                ' class surfaceScalarField;\n object motionReferenceDiffusivity;\n}\n'
                'dimensions [0 0 0 0 0 0 0];\n'
                'internalField nonuniform List<scalar>\n3\n(\n'
            ).encode("ascii")
            trailing=b'\n)\n;\nboundaryField { bladeInterface { type calculated; } }\n'
            values=[5931.11453589184,6785.157856,8272.74259869362]
            p.write_bytes(header+struct.pack("<3d",*values)+trailing)
            data,start,end,read=m.field_values(p)
            self.assertEqual(data[:start],header)
            self.assertEqual(data[end:],trailing)
            self.assertEqual(read,values)
            changed=[x*1.2 for x in read]
            payload=m.encode_field_payload(data,changed)
            self.assertEqual(len(payload),3*8)
            p.write_bytes(data[:start]+payload+data[end:])
            out,lo,hi,decoded=m.field_values(p)
            self.assertEqual(out[:lo],header)
            self.assertEqual(out[hi:],trailing)
            for a,b in zip(decoded,changed):
                self.assertAlmostEqual(a,b)
            self.assertNotEqual(m.sha(p),m.hashlib.sha256(data).hexdigest())

    def test_binary_incomplete_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"motionReferenceDiffusivity"
            header=(
                'FoamFile { format binary; arch "LSB;label=32;scalar=64"; '
                'class surfaceScalarField; }\n'
                'internalField nonuniform List<scalar>\n2\n(\n'
            ).encode("ascii")
            p.write_bytes(header+struct.pack("<1d",42)+b'\n)\n;\n')
            with self.assertRaises(RuntimeError):
                m.field_values(p)

    def test_actual_local_face_patch_is_scoped(self):
        # Mock a rank with the six known incident faces, without HPCC access.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            fluid=root/"runs/hpcc-implicit-002/fluid"
            poly=fluid/"processor5/constant/polyMesh"
            poly.mkdir(parents=True)
            n=11908
            owner=[0]*(n+1)
            nbr=[1]*n
            for fid, other in zip(sorted(m.EXPECTED_FACES),
                                  sorted(m.EXPECTED_NEIGHBOURS)):
                owner[fid]=m.CELL
                nbr[fid]=other
            (poly/"owner").write_text(
                HEADER+str(len(owner))+"\n(\n"+
                "\n".join(map(str,owner))+"\n)\n")
            (poly/"neighbour").write_text(
                HEADER+str(len(nbr))+"\n(\n"+
                "\n".join(map(str,nbr))+"\n)\n")
            field=fluid/"processor5/constant/motionReferenceDiffusivity"
            original=(
                "FoamFile {version 2.0; format ascii; class surfaceScalarField;}\n"
                "dimensions [0 0 0 0 0 0 0];\n"
                f"internalField nonuniform List<scalar>\n{n}\n(\n"+
                "\n".join(["6000"]*n)+"\n)\n;\n"
                "boundaryField {}\n"
            )
            field.write_text(original)
            summary=m.patch_private_stage(fluid,1.20,8)
            self.assertEqual(summary["changed_internal_faces"],6)
            self.assertEqual(m.field_values(field)[-1].count(6000),n-6)
            self.assertTrue((fluid.parent/"LOCAL_ALE_REPAIR96764.json").is_file())
            self.assertEqual(summary["original_sha256"],m.hashlib.sha256(original.encode()).hexdigest())


    def test_pinned_core_resolution_without_recursive_hpc_scan(self):
        source=HERE.parent/"clean-production/segment.py"
        self.assertTrue(source.is_file())
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"code-v5").mkdir()
            target=root/"code-v4/segment.py"
            shutil.copy2(source,target)
            self.assertEqual(m.find_core(root),target)
            target.write_bytes(target.read_bytes()+b"\n# integrity test\n")
            with self.assertRaisesRegex(RuntimeError,"PINNED_FSI_SEGMENT_CORE_GIT_BLOB_MISMATCH"):
                m.find_core(root)
            target.unlink()
            with self.assertRaisesRegex(RuntimeError,"PINNED_EXISTING_FSI_SEGMENT_CORE_NOT_FOUND"):
                m.find_core(root)

    def test_native_python_wrapper_and_slurm_dispatch(self):
        original = HERE/"run-96764-container.sh"
        self.assertTrue(original.is_file())
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            code = root/"code-v5"
            code.mkdir()
            wrapper = code/"run-96764-container.sh"
            shutil.copy2(original,wrapper)
            self.assertEqual(m.native_wrapper(root),wrapper)
            fake_image = root/"seagrass-fsi-ompi507-scotch-time.sif"
            fake_image.write_bytes(b"synthetic only")
            script = root/"repair96764.py"
            script.write_text("print('test')\n")
            with mock.patch.object(m.Path,"home",return_value=root):
                cmd=m.native_batch_command(root,script,"--run-job")
            self.assertIn(" /bin/bash ",cmd)
            self.assertIn("run-96764-container.sh",cmd)
            self.assertIn(" --run-job",cmd)
            self.assertNotIn("bash -c",cmd)
            self.assertNotIn("/bin/bash "+str(script),cmd)
            wrapper.write_text(wrapper.read_text()+"\n# modified\n")
            with self.assertRaisesRegex(RuntimeError,"NATIVE_PYTHON_WRAPPER_GIT_BLOB_MISMATCH"):
                m.native_wrapper(root)

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

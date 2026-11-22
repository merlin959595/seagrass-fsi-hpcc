#!/usr/bin/env python3
"""Offline synthetic tests of one sign-directed C2 minus 2 percent bed patch."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

bed=load(HERE/"continue-c2-minus2percent-native-fsi.py","c2_minus2p_bed2758")
legacy=load(HERE/"repair96764.py","frozen_fsi_parser")

HEAD='FoamFile { version 2.0; format ascii; class labelList; }\n'

class C2Minus2PercentNativeContinuationTests(unittest.TestCase):
    def test_smooth(self):
        self.assertEqual(bed.smooth(0,6),1.)
        self.assertEqual(bed.smooth(6,6),0.)
        self.assertGreater(bed.smooth(2,6),bed.smooth(4,6))
        self.assertGreater(bed.smooth(4,6),0.)

    def synthetic(self,root,processor_overlap=False):
        poly=root/"constant/polyMesh"
        poly.mkdir(parents=True)
        n=11908
        owner=[0]*(n+1)
        nbr=[1]*n
        for fid,other in zip(sorted(bed.EXPECTED_NEG_FACES),
                             sorted(bed.EXPECTED_NEG_NEIGHBORS)):
            owner[fid]=bed.NEG_CENTER
            nbr[fid]=other
        # Force the exact seven-hop path from centre3535 to 2758.
        # 2758 -> 2799 -> 2921 -> 3043 -> 3165 -> 3287 -> 3409 -> 3535
        negatives=[(2799,2921),(2921,3043),(3043,3165),
                   (3165,3287),(3287,3409)]
        for fid,(a,b) in enumerate(negatives,100):
            owner[fid]=a;nbr[fid]=b
        oldfaces=[11491,11899,11901,11903,11905,11907]
        other=[3409,3531,3532,3533,3534,20547]
        for fid,neighbor in zip(oldfaces,other):
            owner[fid]=3535;nbr[fid]=neighbor
        (poly/"owner").write_text(HEAD+str(len(owner))+"\n(\n"+
                                   "\n".join(map(str,owner))+"\n)\n")
        (poly/"neighbour").write_text(HEAD+str(len(nbr))+"\n(\n"+
                                       "\n".join(map(str,nbr))+"\n)\n")
        # A processor patch that touches the target must prevent submission.
        if processor_overlap:
            owner[n]=2799
            (poly/"owner").write_text(HEAD+str(len(owner))+"\n(\n"+
                                       "\n".join(map(str,owner))+"\n)\n")
        patch_kind="processor" if processor_overlap else "wall"
        (poly/"boundary").write_text("FoamFile { class polyBoundaryMesh; }\n1\n(\n"
                                      f"testpatch\n{{type {patch_kind};nFaces 1;"
                                      f"startFace {n};}}\n)\n")
        field=root/"constant/motionReferenceDiffusivity"
        field.write_text("FoamFile {version 2.0; format ascii; "
                         "class surfaceScalarField;}\n"
                         f"internalField nonuniform List<scalar>\n{n}\n(\n"+
                         "\n".join(["6000"]*n)+"\n)\n;\n"
                         "boundaryField{}\n")
        return poly,field

    def test_distinct_target_and_prior_c2_weights(self):
        with tempfile.TemporaryDirectory() as folder:
            poly,field=self.synthetic(Path(folder))
            raw,a,b,before,after,info=bed.plan(poly,field,legacy)
            self.assertEqual(info["actual_concave_cell"],2758)
            self.assertEqual(len(info["cell2758_incident_face_factors"]),6)
            for x in info["cell2758_incident_face_factors"]:
                self.assertAlmostEqual(x["relative_to_C2"],.98)
            self.assertAlmostEqual(after[11491]/before[11491],.85,places=12)
            # Old C2 +Y profile also overlaps this face by a small amount,
            # so total source->new ratio is NOT exactly 0.98. The
            # exact 0.98 criterion is already verified relative to C2.
            row=next(k for k in info["cell2758_incident_face_factors"] if k["face"]==9315)
            self.assertAlmostEqual(after[9315]/before[9315],
                                   row["c2_multiplier"]*.98,places=12)
            self.assertLess(min(after),min(before))
            self.assertGreater(info["changed_internal_faces_negative_region"],6)
            self.assertTrue(info["processor_patch_overlap"] is False)
            self.assertEqual(raw[:a].split(b"internalField")[0].split(b"FoamFile")[0],b"")

    def test_refuse_processor_boundary_overlap(self):
        with tempfile.TemporaryDirectory() as folder:
            poly,field=self.synthetic(Path(folder),processor_overlap=True)
            with self.assertRaisesRegex(RuntimeError,"TOUCHES_PROCESSOR_PATCH"):
                bed.plan(poly,field,legacy)

if __name__=="__main__": unittest.main()

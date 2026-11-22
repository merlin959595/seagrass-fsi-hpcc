#!/usr/bin/env python3
"""Unit test: exact counterfactual projection decomposition with large ALE motion."""
import importlib.util
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

aud=load(HERE/"audit-cell2758-geometry-readonly.py","bed2758_aud")
cmp=load(HERE/"compare-98512-and-c2-cell2758.py","bed2758_compare")

class ExactLargeMotionAttributionTests(unittest.TestCase):
    def test_1mm_nonuniform_motion_exact_telescope(self):
        # Synthetic, regular hexahedral cell with nonuniform ~1 mm motion
        # of four moving face vertices while others are fixed. Test exercises
        # large deformation on nonparallel faces, not just a linear dot product.
        xyz=[(0.,0.,0.),(.01,0.,0.),(.01,.01,0.),(0.,.01,0.),
             (0.,0.,.01),(.01,0.,.01),(.01,.01,.01),(0.,.01,.01)]
        moved=list(xyz)
        moved[0]=(.0010,0.,-.0003)
        moved[1]=(.0109,0.,-.0002)
        moved[4]=(.0011,0.,.0098)
        moved[5]=(.0103,0.,.0097)
        face_a=[0,1,5,4]
        face_b=[0,3,2,1]
        result=cmp.exact_vertex_contribution(aud,xyz,moved,face_a,face_b,1)
        self.assertEqual(result["number_of_moving_vertices"],4)
        self.assertEqual(result["number_of_vertex_orders"],24)
        self.assertLess(abs(result["closure_error_m"]),1e-12)
        self.assertEqual(set(result["vertex_contributions_m"]),set(face_a+face_b))
        self.assertGreater(sum(abs(v) for v in result["vertex_contributions_m"].values()),0.)

    def test_no_motion_all_zero(self):
        xyz=[(0.,0.,0.),(1.,0.,0.),(1.,1.,0.),(0.,1.,0.),
             (0.,0.,1.),(1.,0.,1.),(1.,1.,1.),(0.,1.,1.)]
        out=cmp.exact_vertex_contribution(aud,xyz,xyz,[0,1,5,4],[0,3,2,1],1)
        self.assertEqual(out["number_of_vertex_orders"],1)
        self.assertEqual(out["sum_vertex_contributions_m"],0.)
        self.assertEqual(out["closure_error_m"],0.)

if __name__=="__main__":
    unittest.main()

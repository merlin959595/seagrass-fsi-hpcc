#!/usr/bin/env python3
"""Read-only two-snapshot ALE face-plane forensics for proven cell 2758.

Source: private checkMesh copy of failed 97576 candidate 2.
Never writes a file, never invokes a solver, never changes a checkpoint.
Uses native mesh owner/neighbour/faces/points at exactly 0.5805/0.58075.
"""
from collections import deque
from pathlib import Path
import array
import math
import os
import re
import struct
import sys

RANK=5
FAIL_CELL=2758
PRIOR_CENTER=3535
TIMES=("0.5805","0.58075")

def foam_header(data):
    m=re.search(rb"FoamFile\s*\{[^}]*\}",data[:8192],re.S)
    if not m: raise ValueError("OpenFOAM header missing")
    h=m.group()
    typ=re.search(rb"\bclass\s+(\w+)\s*;",h)
    fmt=re.search(rb"\bformat\s+(\w+)\s*;",h)
    arch=re.search(rb'arch\s+"([^"]+)"',h)
    if not (typ and fmt): raise ValueError("FoamFile class/format missing")
    a=arch.group(1) if arch else b"LSB;label=32;scalar=64"
    width=8 if b"label=64" in a else 4
    endian=">" if b"MSB" in a else "<"
    return m.end(),typ.group(1).decode(),fmt.group(1).decode(),width,endian

def binary_label_block(buf,pos,width,endian,limit=30000000):
    match=re.match(rb"\s*(\d+)\s*\(",buf[pos:pos+70])
    if not match: raise ValueError("binary label list count/open missing at "+str(pos))
    n=int(match.group(1))
    if n<0 or n>limit: raise ValueError("unreasonable label list length "+str(n))
    begin=pos+match.end()
    candidates=[]
    for offset in (0,1,2):
        a=begin+offset
        if offset>0 and buf[begin:a] not in (b"\n",b"\r",b"\r\n"):
            continue
        b=a+n*width
        if b>len(buf):continue
        if re.match(rb"\s*\)",buf[b:b+32]):
            candidates.append((a,b))
    if len(candidates)!=1: raise ValueError("binary payload start ambiguous at "+str(pos)+": "+repr(candidates))
    a,b=candidates[0]
    body=buf[a:b]
    vals=array.array("q" if width==8 else "i")
    vals.frombytes(body)
    import sys as _sys
    if (_sys.byteorder=="little" and endian==">") or (_sys.byteorder=="big" and endian=="<"):
        vals.byteswap()
    trailer=re.match(rb"\s*\)",buf[b:b+32])
    return vals,b+trailer.end()

def labels(path):
    b=path.read_bytes()
    end,typ,fmt,width,endian=foam_header(b)
    match=re.search(rb"(?m)^\s*(\d+)\s*\(",b[end:end+8192])
    if not match: raise ValueError("label list not found: "+str(path))
    start=end+match.start()
    n=int(match.group(1))
    if fmt=="binary":
        v,p=binary_label_block(b,start,width,endian)
        if len(v)!=n:raise ValueError("list count mismatch")
        return v
    body=b[end+match.end():].split(b")",1)[0]
    a=[int(x) for x in body.split()]
    if len(a)!=n:raise ValueError("ascii list count mismatch")
    return a

def faces(path,expected,npoints):
    b=path.read_bytes()
    end,typ,fmt,width,endian=foam_header(b)
    if typ=="faceCompactList" and fmt=="binary":
        first=re.search(rb"(?m)^\s*\d+\s*\(",b[end:end+65536])
        if not first: raise ValueError("compact faces first offsets block missing")
        offsets,pos=binary_label_block(b,end+first.start(),width,endian)
        content,pos=binary_label_block(b,pos,width,endian)
        if len(offsets)!=expected+1 or offsets[0]!=0 or offsets[-1]!=len(content):
            raise ValueError("faceCompactList offset/contents mismatch "+str((len(offsets),len(content),expected)))
        if any(int(offsets[i+1])-int(offsets[i])<3 for i in range(expected)):
            raise ValueError("face has fewer than 3 points")
        return [list(content[offsets[i]:offsets[i+1]]) for i in range(expected)]
    match=re.match(rb"\s*(\d+)\s*\(",b[end:end+70])
    if not match:raise ValueError("non-compact faces list count missing, class="+typ)
    n=int(match.group(1))
    if n!=expected:raise ValueError("face count mismatch")
    pos=end+match.end()
    result=[]
    for i in range(n):
        m=re.match(rb"\s*(\d+)\s*\(",b[pos:pos+50])
        if not m:raise ValueError("face count marker not found at "+str(i))
        size=int(m.group(1));pos+=m.end()
        if size<3 or size>32:raise ValueError("unexpected face vertex count")
        if fmt=="ascii":
            em=re.match(rb"\s*([0-9\s+-]+)\)",b[pos:pos+300])
            if not em:raise ValueError("face ascii vertices not found")
            vals=[int(x) for x in em.group(1).split()]
            pos+=em.end()
        elif fmt=="binary":
            possible=[]
            for off in (0,1,2):
                s=pos+off
                if off and b[pos:s] not in (b"\n",b"\r",b"\r\n"):continue
                e=s+size*width
                tm=re.match(rb"\s*\)",b[e:e+32])
                if tm:
                    vals=array.array("q" if width==8 else "i")
                    vals.frombytes(b[s:e])
                    import sys as _sys
                    if (_sys.byteorder=="little" and endian==">") or (_sys.byteorder=="big" and endian=="<"):
                        vals.byteswap()
                    possible.append((list(vals),e+tm.end()))
            if len(possible)!=1:raise ValueError("binary face payload ambiguous at "+str(i))
            vals,pos=possible[0]
        else:raise ValueError("unknown format "+fmt)
        if len(vals)!=size or any(not 0<=x<npoints for x in vals):
            raise ValueError("invalid face vertices at "+str(i))
        result.append(vals)
    return result

def points(path):
    b=path.read_bytes()
    end,typ,fmt,width,endian=foam_header(b)
    if fmt=="binary":
        m=re.search(rb"(?m)^\s*(\d+)\s*\(",b[end:end+65536])
        if not m:raise ValueError("binary points list count missing")
        n=int(m.group(1));start=end+m.end()
        sample=[]
        for off in (0,1,2):
            a=start+off;z=a+24*n
            if off and b[start:a] not in (b"\n",b"\r",b"\r\n"):continue
            if z<=len(b) and re.match(rb"\s*\)",b[z:z+32]):
                sample.append((a,z))
        if len(sample)!=1:raise ValueError("binary vector payload ambiguous")
        a,z=sample[0]
        out=array.array("d")
        out.frombytes(b[a:z])
        import sys as _sys
        if (_sys.byteorder=="little" and endian==">") or (_sys.byteorder=="big" and endian=="<"):
            out.byteswap()
        if len(out)!=n*3:raise ValueError("point vector size mismatch")
        return [tuple(out[k:k+3]) for k in range(0,len(out),3)]
    m=re.search(rb"(?m)^\s*(\d+)\s*\(",b[end:end+65536])
    if not m:raise ValueError("ascii points count missing")
    n=int(m.group(1))
    body=b[end+m.end():]
    matches=re.findall(rb"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)",body)
    if len(matches)!=n:raise ValueError("ascii points count mismatch")
    return [tuple(float(s) for s in triple) for triple in matches]

def geom(faces_of_cell,vertices,coords,cell,owner):
    ids=sorted(set(v for f in faces_of_cell for v in f[1]))
    pts=[coords[i] for i in ids]
    center=tuple(sum(x[d] for x in pts)/len(pts) for d in range(3))
    bmin=tuple(min(x[d] for x in pts) for d in range(3))
    bmax=tuple(max(x[d] for x in pts) for d in range(3))
    face_report=[]
    for face_i,vs in faces_of_cell:
        poly=[coords[i] for i in vs]
        fc=tuple(sum(p[d] for p in poly)/len(poly) for d in range(3))
        # Newell polygon normal: face orientation in OpenFOAM follows owner.
        nx=ny=nz=0.
        for a,b in zip(poly,poly[1:]+poly[:1]):
            nx+=(a[1]-b[1])*(a[2]+b[2])
            ny+=(a[2]-b[2])*(a[0]+b[0])
            nz+=(a[0]-b[0])*(a[1]+b[1])
        sign=1. if owner[face_i]==cell else -1.
        n=(sign*nx,sign*ny,sign*nz)
        norm=math.sqrt(sum(v*v for v in n))
        if norm<=0: raise ValueError("degenerate face normal "+str(face_i))
        elsewhere=[i for i in ids if i not in vs]
        signed=[(v,sum(n[d]*(coords[v][d]-fc[d]) for d in range(3))/norm)
                for v in elsewhere]
        worst=max(signed,key=lambda x:x[1]) if signed else (None,0.)
        face_report.append({"face_id":face_i,"face_points":list(vs),
                            "max_outside_face_plane_m":worst[1],
                            "worst_other_vertex":worst[0]})
    return {"cell":cell,"vertex_ids":ids,"centroid_m":center,
            "bbox_min_m":bmin,"bbox_max_m":bmax,
            "face_plane_violations":sorted(face_report,key=lambda x:x["max_outside_face_plane_m"],reverse=True)}


def foam_compatible_face_metric(vertices,coords):
    """Area-weighted triangulated face centre and oriented face area vector.

    Same mathematical face geometry used by the OpenFOAM primitiveMesh
    implementation; native v2512 checkMesh remains authoritative.
    """
    p=[coords[k] for k in vertices]
    n=len(p)
    if n<3:raise ValueError("face has fewer than 3 points")
    def sub(a,b):return tuple(a[d]-b[d] for d in range(3))
    def cross(a,b):
        return (a[1]*b[2]-a[2]*b[1],
                a[2]*b[0]-a[0]*b[2],
                a[0]*b[1]-a[1]*b[0])
    def mag(a):return math.sqrt(sum(v*v for v in a))
    if n==3:
        a,b,c=p
        center=tuple((a[d]+b[d]+c[d])/3. for d in range(3))
        normal=tuple(v*0.5 for v in cross(sub(b,a),sub(c,a)))
        return center,normal
    provisional=tuple(sum(x[d] for x in p)/n for d in range(3))
    sum_area=0.0
    weighted=[0.,0.,0.]
    normal=[0.,0.,0.]
    for a,b in zip(p,p[1:]+p[:1]):
        cp=cross(sub(b,a),sub(provisional,a))
        ar=mag(cp)
        sum_area+=ar
        for d in range(3):
            weighted[d]+=ar*(a[d]+b[d]+provisional[d])
            normal[d]+=cp[d]
    if sum_area<=1e-280:
        raise ValueError("degenerate near-zero area face")
    return tuple(v/(3.0*sum_area) for v in weighted),tuple(0.5*x for x in normal)

def cell_face_centre_concavity_proxy(facepairs,coords,cell,owner):
    """For every ordered face pair F_i F_j evaluate projected out-of-plane test.

    Uses face-centre vs face-centre, NOT vertex vs face: V11/OpenFOAM-style
    checkConcaveCells uses these. This is a NUMERIC PROXY, verified only if
    it reproduces the native mesh guard before/after the failure.
    """
    metrics={}
    for face_id,verts in facepairs:
        c,n=foam_compatible_face_metric(verts,coords)
        sign=1 if owner[face_id]==cell else -1
        n=tuple(sign*x for x in n)
        nm=math.sqrt(sum(x*x for x in n))
        if nm<=1e-300:raise ValueError("zero face area "+str(face_id))
        metrics[face_id]=(c,tuple(x/nm for x in n))
    results=[]
    for face_i,_ in facepairs:
        center,normal=metrics[face_i]
        for face_j,_ in facepairs:
            if face_i==face_j:continue
            other,_=metrics[face_j]
            v=tuple(other[d]-center[d] for d in range(3))
            length=math.sqrt(sum(x*x for x in v))
            if length<1e-300:raise ValueError("two face centres coincident")
            projection=sum(normal[d]*v[d] for d in range(3))
            cos_angle=projection/length
            results.append({
                "face_plane_id":face_i,"other_face_centre_id":face_j,
                "signed_outward_projection_m":projection,
                "outward_projection_cosine":cos_angle})
    results.sort(key=lambda x:x["outward_projection_cosine"],reverse=True)
    return results



def critical_face_pair_motion_decomposition(p0,p1,face1,face2,outward_sign=1):
    """Disentangle centre separation from normal rotation at critical faces."""
    fc10,n10=foam_compatible_face_metric(face1,p0)
    fc20,_=foam_compatible_face_metric(face2,p0)
    fc11,n11=foam_compatible_face_metric(face1,p1)
    fc21,_=foam_compatible_face_metric(face2,p1)
    def unit(v):
        length=math.sqrt(sum(x*x for x in v))
        if length<=1e-300: raise ValueError("degenerate face")
        return tuple(x/length for x in v)
    def dot(a,b):return sum(a[i]*b[i] for i in range(3))
    def sub(a,b):return tuple(a[i]-b[i] for i in range(3))
    u0,u1=(tuple(outward_sign*x for x in unit(n10)),
           tuple(outward_sign*x for x in unit(n11)))
    d0,d1=sub(fc20,fc10),sub(fc21,fc11)
    change=sub(d1,d0)
    rotation=sub(u1,u0)
    old=dot(u0,d0);new=dot(u1,d1)
    due_centre=dot(u0,change)
    due_rotation=dot(rotation,d1)
    if abs((new-old)-due_centre-due_rotation)>1e-12:
        raise AssertionError("decomposition does not close")
    return {
       "face1_centre_start_m":fc10,"face1_centre_end_m":fc11,
       "face2_centre_start_m":fc20,"face2_centre_end_m":fc21,
       "face1_outward_normal_start":u0,"face1_outward_normal_end":u1,
       "face1_centre_motion_m":sub(fc11,fc10),
       "face2_centre_motion_m":sub(fc21,fc20),
       "between_face_centre_motion_m":change,
       "start_projection_m":old,"end_projection_m":new,
       "projection_change_m":new-old,
       "due_to_relative_face_centre_m":due_centre,
       "due_to_face1_normal_rotation_m":due_rotation,
       "face1_normal_angle_deg":math.degrees(math.acos(max(-1,min(1,dot(u0,u1))))),
    }


def boundary_patches(path,n_faces,n_internal):
    """Read standard text OpenFOAM processor boundary dictionary, no writes."""
    txt=path.read_text(errors="strict")
    txt=re.sub(r"/\*.*?\*/","",txt,flags=re.S)
    txt=re.sub(r"//[^\n]*","",txt)
    pat=re.compile(r"(?ms)^\s*([A-Za-z_][\w.-]*)\s*\{([^{}]*)\}")
    result=[]
    for m in pat.finditer(txt):
        name,body=m.group(1),m.group(2)
        a=re.search(r"\bnFaces\s+(\d+)\s*;",body)
        b=re.search(r"\bstartFace\s+(\d+)\s*;",body)
        if not (a and b):continue
        num,start=int(a.group(1)),int(b.group(1))
        kind=re.search(r"\btype\s+([^\s;]+)\s*;",body)
        if start<n_internal or start+num>n_faces:
            raise ValueError("boundary patch invalid face range "+str((name,start,num,n_internal,n_faces)))
        result.append((name,kind.group(1) if kind else "type-unknown",start,num))
    if not result:raise ValueError("no boundary patches found "+str(path))
    ranges=sorted((start,start+n,name) for name,kind,start,n in result)
    if ranges[0][0]!=n_internal or ranges[-1][1]!=n_faces:
        raise ValueError("boundary coverage does not match face labels")
    for (_,end,_),(nxt,_,_) in zip(ranges,ranges[1:]):
        if end!=nxt:raise ValueError("boundary face ranges not contiguous")
    return result

def projection_of_face_pair(coords,f1,f2,sign):
    fc,n=foam_compatible_face_metric(f1,coords)
    oc,_=foam_compatible_face_metric(f2,coords)
    n=tuple(sign*v for v in n)
    nm=math.sqrt(sum(v*v for v in n))
    if nm<1e-200:raise ValueError("degenerate face")
    return sum(n[d]*(oc[d]-fc[d]) for d in range(3))/nm

def finite_difference_vertex_attribution(t0,t1,face1,face2,sign,n_steps=16):
    """Integrated first-order coordinate sensitivities along observed path.

    Counterfactual sensitivity is diagnostic; it is not an FSI/mesh-motion
    solver and must not be used to edit any physical displacement directly.
    """
    vs=sorted(set(face1+face2))
    actual=[v for v in vs if any(abs(t1[v][j]-t0[v][j])>1e-15 for j in range(3))]
    score_start=projection_of_face_pair(t0,face1,face2,sign)
    score_end=projection_of_face_pair(t1,face1,face2,sign)
    impact={v:0. for v in vs}
    h=2e-8
    for k in range(n_steps):
        alpha=(k+0.5)/n_steps
        interm=list(t0)
        for v in actual:
            interm[v]=tuple(t0[v][j]+alpha*(t1[v][j]-t0[v][j]) for j in range(3))
        for v in actual:
            for axis in range(3):
                dv=t1[v][axis]-t0[v][axis]
                if abs(dv)<1e-15:continue
                original=interm[v]
                moved=list(original)
                moved[axis]+=h
                interm[v]=tuple(moved)
                plus=projection_of_face_pair(interm,face1,face2,sign)
                moved[axis]-=2*h
                interm[v]=tuple(moved)
                minus=projection_of_face_pair(interm,face1,face2,sign)
                interm[v]=original
                impact[v]+=(plus-minus)*dv/(2*h*n_steps)
    total=sum(impact.values())
    error=total-(score_end-score_start)
    return {
        "start_projection_m":score_start,"end_projection_m":score_end,
        "observed_projection_change_m":score_end-score_start,
        "sensitivity_sum_m":total,"closure_error_m":error,
        "vertex_contributions_m":dict(sorted(impact.items(),key=lambda kv:abs(kv[1]),reverse=True)),
    }

def prior_face_gain_profile(owner,neighbor,graph,centre,faces_of_cell,gain=0.85,rings=8):
    distances={centre:0}
    queue=deque([centre])
    while queue:
        node=queue.popleft()
        if distances[node]>=rings:continue
        for nb in graph.get(node,()):
            if nb not in distances:
                distances[nb]=distances[node]+1
                queue.append(nb)
    result=[]
    for fi in faces_of_cell:
        if fi>=len(neighbor):
            result.append((fi,"boundary_face_not_modified_by_prior_internal_field",1.))
            continue
        near=min(distances.get(int(owner[fi]),rings+1),
                 distances.get(int(neighbor[fi]),rings+1))
        if near>=rings:
            factor=1.
        else:
            q=1.-near/rings
            factor=1.+(gain-1.)*q*q*(3.-2.*q)
        result.append((fi,"nearest_distance_"+str(near),factor))
    return result

def audit_motion_constraints(proc,mesh_faces,owner,neighbor,graph,t0,t1):
    faces_of_cell=[i for i,o in enumerate(owner) if o==FAIL_CELL]
    faces_of_cell.extend(i for i,n in enumerate(neighbor) if n==FAIL_CELL)
    observed_patch_vertices=sorted(set(v for fi in faces_of_cell for v in mesh_faces[fi]))
    patches=boundary_patches(proc/"constant/polyMesh/boundary",len(owner),len(neighbor))
    membership={v:set() for v in observed_patch_vertices}
    for pname,ptype,start,nfaces in patches:
        for fi in range(start,start+nfaces):
            for v in mesh_faces[fi]:
                if v in membership:
                    membership[v].add((pname,ptype))
    for v in observed_patch_vertices:
        vector=tuple(t1[v][j]-t0[v][j] for j in range(3))
        print("CELL2758_VERTEX_CONSTRAINT_AUDIT",v,
              "start_m",t0[v],"end_m",t1[v],
              "delta_m",vector,
              "delta_um",tuple(x*1e6 for x in vector),
              "boundary_patch_membership",sorted(membership[v]))
    print("ORIGINAL_C2_GAIN085_FACE_FACTORS",
          prior_face_gain_profile(owner,neighbor,graph,PRIOR_CENTER,faces_of_cell))
    fi,fj=9315,9306
    if not ((owner[fi]==FAIL_CELL or neighbor[fi]==FAIL_CELL) and
            (owner[fj]==FAIL_CELL or neighbor[fj]==FAIL_CELL)):
        raise ValueError("critical pair not on expected cell")
    sign=1 if owner[fi]==FAIL_CELL else -1
    contributions=finite_difference_vertex_attribution(
        t0,t1,mesh_faces[fi],mesh_faces[fj],sign)
    print("CELL2758_VERTEX_PROJECTION_SENSITIVITY",contributions)
    if abs(contributions["closure_error_m"])>5e-9:
        raise RuntimeError("finite difference sensitivity did not close - no repair guidance")
    print("NO_MODIFICATIONS_NO_RESTART_NO_SLURM; SENSITIVITY_NOT_NATIVE_SOLVER")

def main():
    if not os.environ.get("USER"):raise RuntimeError("USER missing")
    d=Path("/data/icto")/os.environ["USER"]/"seagrass-fsi558-runs.sNIpi9/diagnostics/native-concavity-97576-c2"
    proc=d/"processor5"
    s=proc/"constant/polyMesh"
    owner=labels(s/"owner")
    neighbor=labels(s/"neighbour")
    if len(owner)<len(neighbor):raise ValueError("owner smaller than neighbour")
    graph={}
    for a,b in zip(owner[:len(neighbor)],neighbor):
        graph.setdefault(int(a),set()).add(int(b))
        graph.setdefault(int(b),set()).add(int(a))
    q=deque([PRIOR_CENTER]);dist={PRIOR_CENTER:0};prev={}
    while q:
        node=q.popleft()
        if node==FAIL_CELL:break
        for nxt in graph.get(node,[]):
            if nxt not in dist:
                dist[nxt]=dist[node]+1;prev[nxt]=node;q.append(nxt)
    if FAIL_CELL not in dist:raise RuntimeError("target cell unreachable from old center")
    route=[FAIL_CELL]
    while route[-1]!=PRIOR_CENTER:route.append(prev[route[-1]])
    route.reverse()
    print("CONFIRMED_FAILURE rank=5 cell=2758 at=0.580750s; prior_patch_center_cell=3535")
    print("TOPOLOGICAL_DISTANCE",dist[FAIL_CELL],"RINGS, PATH",route)
    print("PRIOR_8_RING_SMOOTH_MODIFICATION_CAN_DIRECTLY_TOUCH_CELL",dist[FAIL_CELL]<8)
    print("NOTE: a face can be modified if its other endpoint is within radius; inspect face ids.")
    for cell in (FAIL_CELL,PRIOR_CENTER):
        incident=[k for k,o in enumerate(owner) if o==cell]
        incident.extend(k for k,n in enumerate(neighbor) if n==cell)
        print("CELL",cell,"INCIDENT_FACE_IDS",incident,"NEIGHBOURS",sorted(graph.get(cell,())))
    both={}
    first_points=points(proc/"0.5805/polyMesh/points")
    second_points=points(proc/"0.58075/polyMesh/points")
    if len(first_points)!=len(second_points):raise RuntimeError("point count changes across snapshots")
    mesh_faces=faces(s/"faces",len(owner),len(first_points))
    # Re-check compact face vertex index bounds before geometry calculations.
    if any(any(p<0 or p>=len(first_points) for p in face) for face in mesh_faces):
        raise ValueError("face point out of range")
    for cell in (FAIL_CELL,PRIOR_CENTER):
        idx=[i for i,o in enumerate(owner) if o==cell]
        idx.extend(i for i,n in enumerate(neighbor) if n==cell)
        facepairs=[(i,mesh_faces[i]) for i in idx]
        info=[]
        for t,coords in zip(TIMES,(first_points,second_points)):
            r=geom(facepairs,None,coords,cell,owner)
            info.append(r)
            print(f"CELL_{cell}_AT_{t}_CENTER_m",r["centroid_m"])
            print(f"CELL_{cell}_AT_{t}_BBOX_m",r["bbox_min_m"],r["bbox_max_m"])
            for f in r["face_plane_violations"][:4]:
                print("FACE_PLANE_DIAG",cell,t,f)
            proxy=cell_face_centre_concavity_proxy(facepairs,coords,cell,owner)
            print("OPENFOAM_STYLE_FACE_CENTRE_MAX",cell,t,proxy[0])
            for pair in proxy[:5]:
                print("FACE_CENTRE_PAIR",cell,t,pair)
            predicted=proxy[0]["outward_projection_cosine"]>-1.0e-6
            print("FACE_CENTRE_PROXY_CONCAVE_AT_REFERENCE_1e-6",cell,t,predicted)
            if cell==2758:
                expected=(t=="0.58075")
                if predicted!=expected:
                    print("WARNING_NATIVE_CHECKMESH_DISAGREES_WITH_FACE_CENTRE_PROXY; DO_NOT_USE_PAIR_AS_REPAIR_TARGET",cell,t)

        vids=info[0]["vertex_ids"]
        motions=sorted(
            [(i,math.dist(first_points[i],second_points[i])) for i in vids],
            key=lambda x:x[1],reverse=True)
        print("CELL_VERTEX_MOTION_0.5805_TO_0.58075_m",cell,motions)
    # Pair whose projection sign flips and whose mesh snapshot is concave.
    f1,f2=9315,9306
    if not ((owner[f1]==FAIL_CELL or neighbor[f1]==FAIL_CELL) and
            (owner[f2]==FAIL_CELL or neighbor[f2]==FAIL_CELL)):
        raise RuntimeError("Unexpected face membership; no inferred repair")
    sign=1 if owner[f1]==FAIL_CELL else -1
    metrics=critical_face_pair_motion_decomposition(first_points,second_points,
                                                     mesh_faces[f1],mesh_faces[f2],
                                                     outward_sign=sign)
    print("CRITICAL_PAIR_9315_TO_9306_BREAKDOWN",metrics)
    for vid in sorted(set(mesh_faces[f1]+mesh_faces[f2])):
        d=tuple(second_points[vid][i]-first_points[vid][i] for i in range(3))
        print("CRITICAL_VERTEX_VECTOR_m",vid,d,"magnitude_m",math.sqrt(sum(x*x for x in d)))

    if "--constraints" in sys.argv:
        audit_motion_constraints(proc,mesh_faces,owner,neighbor,graph,first_points,second_points)
    print("EXACT_CELL_ID_AND_GEOMETRY_IDENTIFIED; NO_MESH_OR_FSI_MODIFICATIONS")
    print("NOTE: face-plane distances are a geometric aid, not a substitute for native checkMesh verdict.")


def self_test():
    import tempfile
    head=lambda cls: (
        b'FoamFile\n{\n version 2.0;\n format binary;\n'
        +b' arch "LSB;label=32;scalar=64";\n class '+cls.encode()
        +b';\n}\n// banner between header and data\n')
    b32=lambda values: struct.pack("<"+str(len(values))+"i",*values)
    block=lambda vals: str(len(vals)).encode()+b"\n(\n"+b32(vals)+b"\n)\n"
    with tempfile.TemporaryDirectory() as folder:
        p=Path(folder)
        f=p/"faces"
        f.write_bytes(head("faceCompactList")+block([0,4,8])+block([0,1,2,3,4,5,6,7]))
        assert faces(f,2,8)==[[0,1,2,3],[4,5,6,7]]
        o=p/"owner"
        o.write_bytes(head("labelList")+block([0,1,2,3]))
        assert list(labels(o))==[0,1,2,3]
        pt=p/"points"
        vals=[float(x) for x in range(24)]
        pt.write_bytes(head("vectorField")+b"8\n(\n"+struct.pack("<24d",*vals)+b"\n)\n")
        actual=points(pt)
        assert len(actual)==8 and actual[0]==(0.,1.,2.) and actual[-1]==(21.,22.,23.)
        assert foam_header(f.read_bytes())[1]=="faceCompactList"
    cube=[
      (0.,0.,0.),(1.,0.,0.),(1.,1.,0.),(0.,1.,0.),
      (0.,0.,1.),(1.,0.,1.),(1.,1.,1.),(0.,1.,1.)]
    faceList=[
      [0,3,2,1],[4,5,6,7],[0,4,7,3],
      [1,2,6,5],[0,1,5,4],[3,7,6,2]]
    assert abs(foam_compatible_face_metric(faceList[0],cube)[0][2])<1e-13
    score=cell_face_centre_concavity_proxy(list(enumerate(faceList)),cube,0,[0]*6)
    assert all(x["outward_projection_cosine"]<0 for x in score)
    moved=[tuple(v) for v in cube]
    moved[4]=(0.,0.,1.000001)
    details=critical_face_pair_motion_decomposition(cube,moved,faceList[0],faceList[1])
    assert abs(details["projection_change_m"]-
               details["due_to_relative_face_centre_m"]-
               details["due_to_face1_normal_rotation_m"])<1e-12
    attrib=finite_difference_vertex_attribution(cube,moved,faceList[0],faceList[1],1)
    assert abs(attrib["closure_error_m"])<1e-10, attrib
    with tempfile.TemporaryDirectory() as pdir:
        boundary=Path(pdir)/"boundary"
        boundary.write_text('FoamFile { class polyBoundaryMesh; }\n2\n(\n'
                            'fixed\n{\n type wall;\n nFaces 2;\n startFace 6;\n}\n'
                            'remote\n{\n type processor;\n nFaces 2;\n startFace 8;\n}\n)\n')
        patches=boundary_patches(boundary,10,6)
        assert len(patches)==2 and patches[1][1]=="processor"
    print("ALE_CELL2758_VERTEX_SENSITIVITY_AND_BOUNDARY_PARSER_SELFTEST_PASS")
    print("ALE_CELL2758_PAIR_MOTION_DECOMPOSITION_SELFTEST_PASS")
    print("ALE_CELL2758_CUBE_FACE_CENTRE_CONCAVITY_TEST_PASS")
    print("ALE_CELL2758_STDLIB_BINARY_FACE_PARSER_SELFTEST_PASS")

if __name__=="__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    try:main()
    except Exception as e:
        print("READONLY_GEOMETRY_AUDIT_FAILED",type(e).__name__,str(e),file=sys.stderr)
        raise

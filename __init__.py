bl_info = {
    "name": "Motion‑Path Creator",
    "author": "Blender Bob",
    "version": (2, 0, 4),
    "blender": (4, 2, 0),
    "description": "Create object / bone / vertex motion paths with coloured icospheres",
    "category": "Animation",
}

import bpy
import bmesh
from mathutils import Vector
from bpy.props import *
import random
from colorsys import hsv_to_rgb

def random_saturated_color():
    h = random.random()             # Random hue [0, 1]
    s = 1.0                         # Full saturation
    v = 1.0                         # Full brightness
    r, g, b = hsv_to_rgb(h, s, v)
    return (r, g, b, 1.0)

# ────────────────────────────────────────────────────────────────────────────────
# Data Structures
# ────────────────────────────────────────────────────────────────────────────────

def desaturate_color(color, factor):
    from colorsys import rgb_to_hsv, hsv_to_rgb
    r, g, b = color[:3]
    h, s, v = rgb_to_hsv(r, g, b)
    s *= factor
    r2, g2, b2 = hsv_to_rgb(h, s, v)
    return (r2, g2, b2, color[3])

def update_path_color(self, context):
    name = self.name
    col = self.color
    ghost_col = desaturate_color(col, 0.5)
    
    # Update original material
    mat_name = f"MP_Mat_{name}"
    mat = bpy.data.materials.get(mat_name)
    if mat and mat.use_nodes:
        bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf:
            bsdf.inputs['Base Color'].default_value = col
    
    # Update ghost material if exists
    ghost_mat_name = f"MP_Mat_{name}_Ghost"
    ghost_mat = bpy.data.materials.get(ghost_mat_name)
    if ghost_mat and ghost_mat.use_nodes:
        bsdf = next((n for n in ghost_mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf:
            bsdf.inputs['Base Color'].default_value = ghost_col
    
    # Update object colors
    for obj in bpy.data.objects:
        if obj.get("motion_path_addon_sphere") and obj.parent:
            if obj.parent.name == name:
                obj.color = col
            elif obj.parent.name == f"{name}_Ghost":
                obj.color = ghost_col


class MotionPathEntry(bpy.types.PropertyGroup):
    name: StringProperty()
    color: FloatVectorProperty(
        subtype='COLOR',
        size=4,
        default=(1, 0, 1, 1),
        min=0.0,
        max=1.0,
        update=update_path_color
    )
    show_markers: BoolProperty(default=True)
    locked: BoolProperty(default=True)
    ghosted: BoolProperty(default=False)
    visible: BoolProperty(default=True)
    source_type: StringProperty()
    object_name: StringProperty()
    markers_on_keyframes_only: BoolProperty(default=False)
    previous_show_markers: BoolProperty(default=True)


class MotionPathSettings(bpy.types.PropertyGroup):
    use_timeline: BoolProperty(name="Use Timeline", default=True)
    start_frame: IntProperty(name="Start", default=1, min=1)
    end_frame: IntProperty(name="End", default=250, min=1)

    icosphere_radius: FloatProperty(
        name="Radius",
        default=0.01,
        min=0.001,
        max=10.0,
        update=lambda self, ctx: resize_icospheres(ctx)
    )

    marker_step: IntProperty(
        name="Steps",
        default=1,
        min=1,
        max=200,
        description="Interval between markers"
    )

    paths: CollectionProperty(type=MotionPathEntry)
    active_path_index: IntProperty()


# ────────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────────

def get_frame_range(context):
    s = context.scene.motion_path_settings
    return (context.scene.frame_start, context.scene.frame_end) if s.use_timeline else (s.start_frame, s.end_frame)


def resize_icospheres(context):
    radius = context.scene.motion_path_settings.icosphere_radius
    for obj in context.scene.objects:
        if obj.get("motion_path_addon_sphere"):
            obj.scale = (radius, radius, radius)


def set_selectable(obj, state: bool):
    obj.hide_select = not state


def create_base_icosphere():
    mesh_name = "MotionPathSphereMesh"
    if mesh_name in bpy.data.meshes:
        return bpy.data.meshes[mesh_name]

    mesh = bpy.data.meshes.new(mesh_name)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def find_markers(curve_name):
    return [o for o in bpy.context.scene.objects if o.get("motion_path_addon_sphere") and o.parent and o.parent.name == curve_name]


def delete_path_objects(name):
    objs = [o for o in bpy.data.objects if o.name == name or (o.parent and o.parent.name == name)]
    deleted_mats = set()

    for o in objs:
        mat_name = o.get("motion_path_addon_material")
        if mat_name and mat_name not in deleted_mats:
            mat = bpy.data.materials.get(mat_name)
            if mat:
                bpy.data.materials.remove(mat, do_unlink=True)
                deleted_mats.add(mat_name)

        bpy.data.objects.remove(o, do_unlink=True)

def create_motion_path(obj, start, end, world_matrix, *, v_index=None, bone_name=None, path_data=None, source_type="object"):
    scene = bpy.context.scene
    settings = scene.motion_path_settings
    base_mesh = create_base_icosphere()

    suffix = {
        "object": "MP_O",
        "vertex": "MP_V",
        "bone": "MP_B"
    }.get(source_type, "MP_X")

    if source_type == "vertex" and v_index is not None:
        full_name = f"{obj.name}_{v_index}.{suffix}"
    elif source_type == "bone" and bone_name:
        full_name = f"{obj.name}_{bone_name}.{suffix}"
    else:
        full_name = f"{obj.name}.{suffix}"

    curve_data = bpy.data.curves.new(name=full_name + ".Data", type='CURVE')
    curve_data.dimensions = '3D'
    curve_data.resolution_u = 2

    curve_obj = bpy.data.objects.new(full_name, curve_data)
    curve_obj["is_motion_path"] = True
    scene.collection.objects.link(curve_obj)
    curve_obj.show_in_front = True
    set_selectable(curve_obj, False)

    spline = curve_data.splines.new('POLY')
    spline.points.add(end - start)

    mat_color = path_data.color if path_data else random_saturated_color()
    mat_name = f"MP_Mat_{full_name}"

    if mat_name in bpy.data.materials:
        mat = bpy.data.materials[mat_name]
        if mat.use_nodes:
            bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf:
                bsdf.inputs['Base Color'].default_value = mat_color
    else:
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        output = nodes.new(type='ShaderNodeOutputMaterial')
        bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = mat_color
        bsdf.inputs['Roughness'].default_value = 0.5
        links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

    created_markers = []
    for f in range(start, end + 1):
        scene.frame_set(f)

        if v_index is not None and obj.type == 'MESH':
            pos = world_matrix @ obj.data.vertices[v_index].co
        elif bone_name is not None and obj.type == 'ARMATURE':
            pos = world_matrix @ obj.pose.bones[bone_name].head
        else:
            pos = obj.matrix_world.translation

        spline.points[f - start].co = (*pos, 1.0)

        if (f - start) % settings.marker_step != 0:
            continue

        inst = bpy.data.objects.new(f"{full_name}_Marker#{f}", base_mesh)
        inst.scale = (settings.icosphere_radius,) * 3
        inst.location = pos
        inst.parent = curve_obj
        inst["motion_path_addon_sphere"] = True
        inst["path_id"] = full_name
        inst["motion_path_addon_material"] = mat_name
        set_selectable(inst, False)
        scene.collection.objects.link(inst)
        inst.show_in_front = True
        inst.color = mat_color
        
        # Assign material per object
        if len(inst.material_slots) == 0:
            inst.data.materials.append(None)
        inst.material_slots[0].link = 'OBJECT'
        inst.material_slots[0].material = mat
        
        created_markers.append(inst)

    if not path_data:
        entry = settings.paths.add()
        entry.name = curve_obj.name
        entry.color = mat_color
        entry.locked = True
        entry.source_type = source_type
        entry.object_name = obj.name
        settings.active_path_index = len(settings.paths) - 1
    else:
        path_data.name = curve_obj.name
        path_data.object_name = obj.name


def duplicate_path(path_name):
    original = bpy.data.objects.get(path_name)
    if not original:
        return

    new_curve = original.copy()
    new_curve.data = original.data.copy()
    new_curve.name = f"{path_name}_Ghost"
    new_curve["is_motion_path_ghost"] = True
    set_selectable(new_curve, False)
    bpy.context.scene.collection.objects.link(new_curve)

    for marker in find_markers(path_name):
        new_marker = marker.copy()
        new_marker.data = marker.data
        new_marker.name = marker.name + "_Ghost"
        new_marker.parent = new_curve
        new_marker["motion_path_addon_sphere"] = True
        set_selectable(new_marker, False)
        bpy.context.scene.collection.objects.link(new_marker)


# ────────────────────────────────────────────────────────────────────────────────
# Operators
# ────────────────────────────────────────────────────────────────────────────────
class OBJECT_OT_DeleteAllPaths(bpy.types.Operator):
    bl_idname = "motionpath.delete_all"
    bl_label = "Delete All Paths"

    def execute(self, ctx):
        s = ctx.scene.motion_path_settings

        for path in reversed(s.paths):
            delete_path_objects(path.name)
            delete_path_objects(path.name + "_Ghost")

        s.paths.clear()
        return {'FINISHED'}

class OBJECT_OT_RefreshAllPaths(bpy.types.Operator):
    bl_idname = "motionpath.refresh_all"
    bl_label = "Update All Paths"

    def execute(self, ctx):
        s = ctx.scene.motion_path_settings
        f0, f1 = get_frame_range(ctx)

        for i, path in enumerate(s.paths):
            obj = bpy.data.objects.get(path.object_name)
            if not obj:
                self.report({'WARNING'}, f"Object '{path.object_name}' not found.")
                continue

            # Delete only the original path and its markers (preserve ghost)
            objs_to_delete = [
                o for o in bpy.data.objects
                if (o.name == path.name or (o.parent and o.parent.name == path.name))
                and "_Ghost" not in o.name
            ]

            deleted_mats = set()
            for o in objs_to_delete:
                mat_name = o.get("motion_path_addon_material")
                if mat_name and mat_name not in deleted_mats:
                    mat = bpy.data.materials.get(mat_name)
                    if mat:
                        bpy.data.materials.remove(mat, do_unlink=True)
                        deleted_mats.add(mat_name)
                bpy.data.objects.remove(o, do_unlink=True)

            # Recreate path
            if path.source_type == 'object':
                create_motion_path(obj, f0, f1, obj.matrix_world, path_data=path, source_type='object')

            elif path.source_type == 'vertex':
                if obj.type != 'MESH':
                    self.report({'WARNING'}, f"'{obj.name}' is not a mesh object.")
                    continue

                try:
                    basename = path.name.rsplit(".MP_", 1)[0]
                    v_index = int(basename.rsplit("_", 1)[1])
                except Exception as e:
                    self.report({'WARNING'}, f"Could not parse vertex index from '{path.name}': {e}")
                    continue

                if v_index >= len(obj.data.vertices):
                    self.report({'WARNING'}, f"Vertex index {v_index} out of range for '{obj.name}'.")
                    continue

                print(f"✅ Refreshing vertex path: {path.name} (vertex {v_index})")
                create_motion_path(obj, f0, f1, obj.matrix_world, v_index=v_index, path_data=path, source_type='vertex')

            elif path.source_type == 'bone':
                if obj.type != 'ARMATURE' or not obj.pose.bones:
                    self.report({'WARNING'}, f"'{obj.name}' has no pose bones.")
                    continue

                try:
                    bone_name = path.name.split("_", 1)[1].rsplit(".MP_", 1)[0]
                except Exception as e:
                    self.report({'WARNING'}, f"Could not parse bone name from '{path.name}': {e}")
                    continue

                if bone_name not in obj.pose.bones:
                    self.report({'WARNING'}, f"Bone '{bone_name}' not found in '{obj.name}'.")
                    continue

                print(f"✅ Refreshing bone path: {path.name} (bone '{bone_name}')")
                create_motion_path(obj, f0, f1, obj.matrix_world, bone_name=bone_name, path_data=path, source_type='bone')

        return {'FINISHED'}

class OBJECT_OT_CreateObjectPath(bpy.types.Operator):
    bl_idname = "motionpath.object"
    bl_label = "Object"

    confirm: BoolProperty(default=False)
    confirm_message: StringProperty(default="")

    def get_selected_count(self, context):
        return len(context.selected_objects)

    def invoke(self, context, event):
        count = self.get_selected_count(context)
        if count > 10 and not self.confirm:
            self.confirm_message = f"Are you sure you want to create paths for {count} objects?"
            return context.window_manager.invoke_props_dialog(self)
        return self.execute(context)

    def draw(self, context):
        self.layout.label(text=self.confirm_message)

    def execute(self, ctx):
        if bpy.context.mode != 'OBJECT':
            self.report({'WARNING'}, "Must be in Object Mode to create object paths.")
            return {'CANCELLED'}

        objs = ctx.selected_objects
        if not objs:
            self.report({'WARNING'}, "No selected objects")
            return {'CANCELLED'}

        f0, f1 = get_frame_range(ctx)

        for obj in objs:
            name = f"{obj.name}.MP_O"
            if bpy.data.objects.get(name):
                self.report({'INFO'}, f"Path already exists for {obj.name}")
                continue
            create_motion_path(obj, f0, f1, obj.matrix_world, source_type='object')

        return {'FINISHED'}


class OBJECT_OT_CreateVertexPath(bpy.types.Operator):
    bl_idname = "motionpath.vertex"
    bl_label = "Vertex"

    confirm: BoolProperty(default=False)
    confirm_message: StringProperty(default="")

    def invoke(self, context, event):
        if context.mode != 'EDIT_MESH':
            self.report({'WARNING'}, "Must be in Edit Mode to create vertex paths.")
            return {'CANCELLED'}

        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "No active mesh object")
            return {'CANCELLED'}

        bm = bmesh.from_edit_mesh(obj.data)
        count = len([v for v in bm.verts if v.select])
        if count == 0:
            self.report({'WARNING'}, "No vertex selected")
            return {'CANCELLED'}

        if count > 10 and not self.confirm:
            self.confirm_message = f"Are you sure you want to create paths for {count} vertices?"
            return context.window_manager.invoke_props_dialog(self)
        return self.execute(context)

    def draw(self, context):
        self.layout.label(text=self.confirm_message)

    def execute(self, ctx):
        obj = ctx.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        selected = [v.index for v in bm.verts if v.select]

        bpy.ops.object.mode_set(mode='OBJECT')
        f0, f1 = get_frame_range(ctx)

        created = 0
        for v_idx in selected:
            name = f"{obj.name}_{v_idx}.MP_V"
            if bpy.data.objects.get(name):
                self.report({'INFO'}, f"Path already exists for vertex {v_idx} in '{obj.name}'")
                continue
            create_motion_path(obj, f0, f1, obj.matrix_world, v_index=v_idx, source_type='vertex')
            created += 1

        if created == 0:
            return {'CANCELLED'}

        return {'FINISHED'}

    
class OBJECT_OT_CreateBonePath(bpy.types.Operator):
    bl_idname = "motionpath.bone"
    bl_label = "Bone"

    confirm: BoolProperty(default=False)
    confirm_message: StringProperty(default="")

    def get_selected_count(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.type == 'ARMATURE':
                count += sum(1 for bone in obj.data.bones if bone.select)
        return count

    def invoke(self, context, event):
        count = self.get_selected_count(context)
        if count > 10 and not self.confirm:
            self.confirm_message = f"Are you sure you want to create paths for {count} bones?"
            return context.window_manager.invoke_props_dialog(self)
        return self.execute(context)

    def draw(self, context):
        self.layout.label(text=self.confirm_message)

    def execute(self, ctx):
        armatures = [obj for obj in ctx.selected_objects if obj.type == 'ARMATURE']
        if not armatures:
            self.report({'WARNING'}, "No armatures selected")
            return {'CANCELLED'}

        original_mode = ctx.mode
        f0, f1 = get_frame_range(ctx)
        created = 0

        for arm in armatures:
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.context.view_layer.objects.active = arm
            bpy.ops.object.mode_set(mode='POSE')

            for bone in arm.data.bones:
                if not bone.select:
                    continue

                path_name = f"{arm.name}_{bone.name}.MP_B"
                if bpy.data.objects.get(path_name):
                    self.report({'INFO'}, f"Path already exists for bone '{bone.name}' in '{arm.name}'")
                    continue

                print(f"[DEBUG] Creating bone path: {path_name}")
                create_motion_path(arm, f0, f1, arm.matrix_world, bone_name=bone.name, source_type='bone')
                created += 1

        if original_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=original_mode)

        if created == 0:
            return {'CANCELLED'}

        return {'FINISHED'}


class OBJECT_OT_DeletePath(bpy.types.Operator):
    bl_idname = "motionpath.delete_path"
    bl_label = "Delete Path"
    index: IntProperty()

    def execute(self, ctx):
        s = ctx.scene.motion_path_settings
        path = s.paths[self.index]
        delete_path_objects(path.name)
        delete_path_objects(path.name + "_Ghost")
        s.paths.remove(self.index)
        return {'FINISHED'}

class OBJECT_OT_ToggleLock(bpy.types.Operator):
    bl_idname = "motionpath.toggle_lock"
    bl_label = "Toggle Lock"
    index: IntProperty()

    def execute(self, ctx):
        path = ctx.scene.motion_path_settings.paths[self.index]
        path.locked = not path.locked
        target = bpy.data.objects.get(path.name)
        if target:
            set_selectable(target, not path.locked)
        for m in find_markers(path.name):
            set_selectable(m, not path.locked)
        return {'FINISHED'}


class OBJECT_OT_ToggleMarkers(bpy.types.Operator):
    bl_idname = "motionpath.toggle_markers"
    bl_label = "Toggle Markers"
    index: IntProperty()

    def execute(self, ctx):
        path = ctx.scene.motion_path_settings.paths[self.index]
        path.show_markers = not path.show_markers
        for m in find_markers(path.name):
            m.hide_viewport = not path.show_markers
        return {'FINISHED'}


class OBJECT_OT_GhostPath(bpy.types.Operator):
    bl_idname = "motionpath.ghost_path"
    bl_label = "Ghost Path"
    index: IntProperty()

    def execute(self, ctx):
        path = ctx.scene.motion_path_settings.paths[self.index]
        ghost_name = path.name + "_Ghost"
        ghost_color = desaturate_color(path.color, 0.5)

        if not path.ghosted:
            # Duplicate path and markers
            original = bpy.data.objects.get(path.name)
            if not original:
                return {'CANCELLED'}

            new_curve = original.copy()
            new_curve.data = original.data.copy()
            new_curve.name = ghost_name
            new_curve["is_motion_path_ghost"] = True
            new_curve.hide_select = True
            bpy.context.scene.collection.objects.link(new_curve)

            new_markers = []
            for marker in find_markers(path.name):
                new_marker = marker.copy()
                new_marker.data = marker.data
                new_marker.name = marker.name + "_Ghost"
                new_marker.parent = new_curve
                new_marker["motion_path_addon_sphere"] = True
                new_marker.hide_select = True
                new_marker.color = ghost_color
                bpy.context.scene.collection.objects.link(new_marker)
                new_markers.append(new_marker)
            
            # Create ghost material
            ghost_mat_name = f"MP_Mat_{path.name}_Ghost"
            ghost_mat = bpy.data.materials.new(name=ghost_mat_name)
            ghost_mat.use_nodes = True
            nodes = ghost_mat.node_tree.nodes
            links = ghost_mat.node_tree.links
            nodes.clear()

            output = nodes.new(type='ShaderNodeOutputMaterial')
            bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
            bsdf.inputs['Base Color'].default_value = ghost_color
            bsdf.inputs['Roughness'].default_value = 0.5
            links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
            
            # Assign ghost material to new markers
            for new_marker in new_markers:
                if len(new_marker.material_slots) == 0:
                    new_marker.data.materials.append(None)
                new_marker.material_slots[0].link = 'OBJECT'
                new_marker.material_slots[0].material = ghost_mat
                new_marker["motion_path_addon_material"] = ghost_mat_name

            path.ghosted = True

        else:
            # Delete ghost path and markers
            delete_path_objects(ghost_name)
            path.ghosted = False

        return {'FINISHED'}


class OBJECT_OT_ToggleVisibility(bpy.types.Operator):
    bl_idname = "motionpath.toggle_visibility"
    bl_label = "Toggle Visibility"
    index: IntProperty()

    def execute(self, ctx):
        path = ctx.scene.motion_path_settings.paths[self.index]
        path.visible = not path.visible

        def hide(objname):
            obj = bpy.data.objects.get(objname)
            if obj:
                obj.hide_viewport = not path.visible

        hide(path.name)
        hide(path.name + "_Ghost")
        for m in find_markers(path.name) + find_markers(path.name + "_Ghost"):
            m.hide_viewport = not path.visible

        return {'FINISHED'}
    
class OBJECT_OT_RefreshPath(bpy.types.Operator):
    bl_idname = "motionpath.refresh"
    bl_label = "↻"

    index: IntProperty()

    def execute(self, ctx):
        scene = ctx.scene
        settings = scene.motion_path_settings
        f0, f1 = get_frame_range(ctx)

        path = settings.paths[self.index]
        obj = bpy.data.objects.get(path.object_name)

        if not obj:
            self.report({'WARNING'}, f"Object '{path.object_name}' not found.")
            return {'CANCELLED'}

        # Delete only the original path and its markers (not the ghost)
        objs_to_delete = [
            o for o in bpy.data.objects
            if (o.name == path.name or (o.parent and o.parent.name == path.name))
            and "_Ghost" not in o.name
        ]

        deleted_mats = set()
        for o in objs_to_delete:
            mat_name = o.get("motion_path_addon_material")
            if mat_name and mat_name not in deleted_mats:
                mat = bpy.data.materials.get(mat_name)
                if mat:
                    bpy.data.materials.remove(mat, do_unlink=True)
                    deleted_mats.add(mat_name)
            bpy.data.objects.remove(o, do_unlink=True)

        # Recreate path
        if path.source_type == 'object':
            create_motion_path(obj, f0, f1, obj.matrix_world, path_data=path, source_type='object')

        elif path.source_type == 'vertex':
            if obj.type != 'MESH':
                self.report({'WARNING'}, f"'{obj.name}' is not a mesh object.")
                return {'CANCELLED'}

            try:
                basename = path.name.rsplit(".MP_", 1)[0]
                v_index = int(basename.rsplit("_", 1)[1])
            except Exception as e:
                self.report({'WARNING'}, f"Could not parse vertex index from '{path.name}': {e}")
                return {'CANCELLED'}

            if v_index >= len(obj.data.vertices):
                self.report({'WARNING'}, f"Vertex index {v_index} out of range for '{obj.name}'.")
                return {'CANCELLED'}

            print(f"✅ Refreshing vertex path: {path.name} (vertex {v_index})")
            create_motion_path(obj, f0, f1, obj.matrix_world, v_index=v_index, path_data=path, source_type='vertex')

        elif path.source_type == 'bone':
            try:
                bone_name = path.name.split("_", 1)[1].rsplit(".MP_", 1)[0]
            except:
                self.report({'WARNING'}, f"Invalid bone path name: {path.name}")
                return {'CANCELLED'}
            if bone_name not in obj.pose.bones:
                self.report({'WARNING'}, f"Bone '{bone_name}' not found in '{obj.name}'")
                return {'CANCELLED'}
            create_motion_path(obj, f0, f1, obj.matrix_world, bone_name=bone_name, path_data=path, source_type='bone')

        return {'FINISHED'}

class OBJECT_OT_ToggleKeyframeOnlyMarkers(bpy.types.Operator):
    bl_idname = "motionpath.toggle_keyframe_markers"
    bl_label = "Toggle Keyframe Markers"
    index: IntProperty()

    def execute(self, ctx):
        path = ctx.scene.motion_path_settings.paths[self.index]
        keyframes_only = not path.markers_on_keyframes_only
        path.markers_on_keyframes_only = keyframes_only

        markers = find_markers(path.name)
        obj = bpy.data.objects.get(path.object_name)
        if not obj:
            self.report({'WARNING'}, f"Object '{path.object_name}' not found.")
            return {'CANCELLED'}

        if keyframes_only:
            # Save current state
            path.previous_show_markers = path.show_markers
            path.show_markers = True
            keyframes = set()
            if obj.animation_data and obj.animation_data.action:
                for fcu in obj.animation_data.action.fcurves:
                    keyframes.update(int(k.co.x) for k in fcu.keyframe_points)

            for m in markers:
                m_frame_str = m.name.split("#")[-1] if "#" in m.name else ""
                # To handle possible suffixes like .001, split by '.' and take first part
                try:
                    m_frame = int(m_frame_str.split(".")[0])
                except ValueError:
                    m_frame = None
                m.hide_viewport = m_frame not in keyframes if m_frame is not None else True
        else:
            # Restore previous visibility state
            path.show_markers = path.previous_show_markers
            for m in markers:
                m.hide_viewport = not path.show_markers

        return {'FINISHED'}

# ────────────────────────────────────────────────────────────────────────────────
# UI
# ────────────────────────────────────────────────────────────────────────────────

class VIEW3D_PT_MotionPathPanel(bpy.types.Panel):
    bl_label = "Motion‑Path Creator"
    bl_idname = "VIEW3D_PT_motion_path"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MotionPaths'

    def draw(self, ctx):
        layout = self.layout
        s = ctx.scene.motion_path_settings

        layout.prop(s, "use_timeline")
        if not s.use_timeline:
            layout.prop(s, "start_frame")
            layout.prop(s, "end_frame")
            layout.prop(s, "marker_step")
        else:
            layout.prop(s, "marker_step")

        layout.operator("motionpath.object", icon='OBJECT_DATA')
        layout.operator("motionpath.vertex", icon='VERTEXSEL')
        layout.operator("motionpath.bone", icon='BONE_DATA')
        layout.prop(s, "icosphere_radius")

        if s.paths:
            for i, path in enumerate(s.paths):
                row = layout.row(align=True)
                row.label(text=path.name)
                row2 = row.row(align=True)
                row2.scale_x = 0.35
                row2.prop(path, "color", text="")
                row.operator("motionpath.toggle_visibility", text="", icon='HIDE_OFF' if path.visible else 'HIDE_ON').index = i
                row.operator("motionpath.refresh", text="", icon='FILE_REFRESH').index = i
                row.operator("motionpath.toggle_markers", text="", icon='RADIOBUT_ON' if path.show_markers else 'RADIOBUT_OFF').index = i
                row.operator("motionpath.toggle_keyframe_markers", text="", icon='KEYFRAME_HLT' if path.markers_on_keyframes_only else 'KEYFRAME').index = i
                row.operator("motionpath.toggle_lock", text="", icon='DECORATE_LOCKED' if path.locked else 'DECORATE_UNLOCKED').index = i
                row.operator("motionpath.ghost_path", text="", icon='GHOST_ENABLED' if path.ghosted else 'GHOST_DISABLED').index = i
                row.operator("motionpath.delete_path", text="", icon='X').index = i

            layout.separator()
            layout.operator("motionpath.refresh_all", text="Update All Paths", icon='FILE_REFRESH')
            layout.operator("motionpath.delete_all", text="Delete All Paths", icon='TRASH')

# ────────────────────────────────────────────────────────────────────────────────
# Registration
# ────────────────────────────────────────────────────────────────────────────────

classes = (
    MotionPathEntry,
    MotionPathSettings,
    OBJECT_OT_CreateObjectPath,
    OBJECT_OT_CreateVertexPath,
    OBJECT_OT_CreateBonePath,
    OBJECT_OT_DeletePath,
    OBJECT_OT_ToggleLock,
    OBJECT_OT_ToggleMarkers,
    OBJECT_OT_GhostPath,
    OBJECT_OT_RefreshPath,
    OBJECT_OT_ToggleVisibility,
    VIEW3D_PT_MotionPathPanel,
    OBJECT_OT_RefreshAllPaths,
    OBJECT_OT_DeleteAllPaths,
    OBJECT_OT_ToggleKeyframeOnlyMarkers,

)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.motion_path_settings = PointerProperty(type=MotionPathSettings)

def unregister():
    del bpy.types.Scene.motion_path_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
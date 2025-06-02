bl_info = {
    "name": "Motion‑Path Creator",
    "author": "Blender Bob",
    "version": (1, 2, 0),
    "blender": (4, 2, 0),
    "description": "Create object / bone / vertex motion paths with coloured icospheres",
    "category": "Animation",
}

import bpy
import bmesh
from mathutils import Vector

# ────────────────────────────────────────────────────────────────────────────────
# Property group
# ────────────────────────────────────────────────────────────────────────────────
class MotionPathSettings(bpy.types.PropertyGroup):
    use_timeline: bpy.props.BoolProperty(
        name="Use Timeline",
        description="Use the timeline's start and end frames",
        default=True,
    )
    start_frame: bpy.props.IntProperty(
        name="Start",
        description="Start frame for motion path",
        default=1,
        min=1,
    )
    end_frame: bpy.props.IntProperty(
        name="End",
        description="End frame for motion path",
        default=250,
        min=1,
    )
    icosphere_radius: bpy.props.FloatProperty(
        name="Radius",
        description="Radius of the icosphere",
        default=0.01,
        min=0.001,
        max=1.0,
    )
    icosphere_color: bpy.props.FloatVectorProperty(
        name="Color",
        description="Icosphere display colour",
        default=(1.0, 0.0, 0.6),
        min=0.0,
        max=1.0,
        subtype='COLOR',
    )

# ────────────────────────────────────────────────────────────────────────────────
# Handler – called only when a transform actually changes
# ────────────────────────────────────────────────────────────────────────────────
def update_icospheres(depsgraph):
    """Resize all icospheres to match the current radius setting."""
    scene   = bpy.context.scene
    radius  = scene.motion_path_settings.icosphere_radius
    changed = False

    # Look for any object in the current *scene* that was just transformed
    for upd in depsgraph.updates:
        if isinstance(upd.id, bpy.types.Object) and upd.id.is_updated_transform:
            changed = True
            break

    if not changed:
        return  # nothing relevant changed – exit early

    for obj in scene.objects:
        if obj.get("motion_path_addon_sphere"):
            obj.scale = (radius, radius, radius)

# ────────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ────────────────────────────────────────────────────────────────────────────────
def set_viewport_shading_to_object_color():
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type       = 'SOLID'
                    space.shading.color_type = 'OBJECT'
                    return                    # done – no need to keep looping

def get_frame_range(context):
    s = context.scene.motion_path_settings
    return (context.scene.frame_start, context.scene.frame_end) if s.use_timeline else (s.start_frame, s.end_frame)

def create_base_icosphere(radius, color):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=radius, location=(0, 0, 0))
    sphere = bpy.context.object
    sphere.name = "BaseIcoSphere"
    sphere["motion_path_addon_sphere"] = True
    sphere.hide_render = True
    sphere.color = (*color, 1.0)
    bpy.ops.object.shade_smooth()
    return sphere

def create_motion_path(obj, start, end, world_matrix, *, v_index=None, bone_name=None):
    """Generic creator – supports objects, a single vertex or a single bone."""
    s   = bpy.context.scene.motion_path_settings
    ico = create_base_icosphere(s.icosphere_radius, s.icosphere_color)

    curve_data              = bpy.data.curves.new("MotionPathCurve", 'CURVE')
    curve_data.dimensions   = '3D'
    curve_data.resolution_u = 2
    curve_obj               = bpy.data.objects.new("MotionPath", curve_data)
    curve_obj["is_motion_path"] = True
    bpy.context.scene.collection.objects.link(curve_obj)

    spline = curve_data.splines.new('POLY')
    spline.points.add(end - start)

    for f in range(start, end + 1):
        bpy.context.scene.frame_set(f)

        if v_index is not None and obj.type == 'MESH':
            pos = world_matrix @ obj.data.vertices[v_index].co
        elif bone_name is not None and obj.type == 'ARMATURE':
            pos = world_matrix @ obj.pose.bones[bone_name].head
        else:
            pos = obj.matrix_world.translation

        spline.points[f - start].co = (*pos, 1.0)

        inst              = ico.copy()
        inst.data         = ico.data.copy()
        inst.location     = pos
        inst.parent       = curve_obj
        inst["motion_path_addon_sphere"] = True
        bpy.context.scene.collection.objects.link(inst)

    ico.hide_set(True)

# ────────────────────────────────────────────────────────────────────────────────
# Operators
# ────────────────────────────────────────────────────────────────────────────────
class BonePathOperator(bpy.types.Operator):
    bl_idname = "motionpath.bone"
    bl_label  = "Bone Motion Path"
    bl_description = "Create motion path for the active bone"

    def execute(self, ctx):
        arm = ctx.active_object
        bone = ctx.active_pose_bone
        if not (arm and arm.type == 'ARMATURE' and bone):
            self.report({'ERROR'}, "Select an armature + active bone")
            return {'CANCELLED'}

        f0, f1 = get_frame_range(ctx)
        create_motion_path(arm, f0, f1, arm.matrix_world, bone_name=bone.name)
        set_viewport_shading_to_object_color()
        return {'FINISHED'}

class VertexPathOperator(bpy.types.Operator):
    bl_idname = "motionpath.vertex"
    bl_label  = "Vertex Motion Path"
    bl_description = "Create motion path for the first selected vertex"

    def execute(self, ctx):
        obj = ctx.active_object
        if not (obj and obj.type == 'MESH'):
            self.report({'ERROR'}, "Select a mesh object in Edit‑mode")
            return {'CANCELLED'}

        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode='OBJECT')

        sel = [v.index for v in obj.data.vertices if v.select]
        if not sel:
            self.report({'ERROR'}, "No vertex selected")
            return {'CANCELLED'}

        f0, f1 = get_frame_range(ctx)
        create_motion_path(obj, f0, f1, obj.matrix_world, v_index=sel[0])

        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode='EDIT')

        set_viewport_shading_to_object_color()
        return {'FINISHED'}

class ObjectPathOperator(bpy.types.Operator):
    bl_idname = "motionpath.object"
    bl_label  = "Object Motion Path"
    bl_description = "Create motion path for the active object (any type)"

    def execute(self, ctx):
        obj = ctx.active_object
        if not obj:
            self.report({'ERROR'}, "No active object")
            return {'CANCELLED'}

        f0, f1 = get_frame_range(ctx)
        create_motion_path(obj, f0, f1, obj.matrix_world)
        set_viewport_shading_to_object_color()
        return {'FINISHED'}

class CleanUpOperator(bpy.types.Operator):
    bl_idname = "motionpath.cleanup"
    bl_label  = "Delete All Motion Paths"

    def execute(self, ctx):
        scene = ctx.scene
        spheres = [o for o in scene.objects if o.get("motion_path_addon_sphere")]
        curves  = {o.parent for o in spheres if o.parent and o.parent.get("is_motion_path")}

        for o in spheres + list(curves):
            bpy.data.objects.remove(o, do_unlink=True)

        self.report({'INFO'}, "Motion paths deleted")
        return {'FINISHED'}

# ────────────────────────────────────────────────────────────────────────────────
# UI
# ────────────────────────────────────────────────────────────────────────────────
class MotionPathPanel(bpy.types.Panel):
    bl_label       = "Motion‑Path Creator"
    bl_idname      = "ANIM_PT_motionpath_creator"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'Animation'

    def draw(self, ctx):
        lay = self.layout
        s   = ctx.scene.motion_path_settings

        lay.prop(s, "use_timeline")
        if not s.use_timeline:
            lay.prop(s, "start_frame")
            lay.prop(s, "end_frame")
        lay.prop(s, "icosphere_radius")
        lay.prop(s, "icosphere_color")

        lay.operator("motionpath.bone",   icon='BONE_DATA')
        lay.operator("motionpath.vertex", icon='VERTEXSEL')
        lay.operator("motionpath.object", icon='OBJECT_DATA')
        lay.operator("motionpath.cleanup", icon='X')

# ────────────────────────────────────────────────────────────────────────────────
# Registration helpers
# ────────────────────────────────────────────────────────────────────────────────
classes = (
    MotionPathSettings,
    BonePathOperator,
    VertexPathOperator,
    ObjectPathOperator,
    CleanUpOperator,
    MotionPathPanel,
)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.motion_path_settings = bpy.props.PointerProperty(type=MotionPathSettings)

    # depsgraph handler (registered once, removed on unregister)
    if update_icospheres not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(update_icospheres)

def unregister():
    if update_icospheres in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(update_icospheres)

    del bpy.types.Scene.motion_path_settings
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    register()

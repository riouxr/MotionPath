# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

bl_info = {
    "name": "Motion Path Creator",
    "author": "Blender Bob, Chat GPT",
    "version": (1, 0),
    "blender": (2, 80, 0),
    "description": "Create motion paths for bones, vertices, empties and objects",
    "category": "Animation",
    "support": "COMMUNITY"    
}

import bpy
import bmesh
from mathutils import Vector


class MotionPathSettings(bpy.types.PropertyGroup):
    use_timeline: bpy.props.BoolProperty(
        name="Use Timeline",
        description="Use the timeline's start and end frames",
        default=True
    )
    start_frame: bpy.props.IntProperty(
        name="Start",
        description="Start frame for motion path",
        default=1,
        min=1
    )
    end_frame: bpy.props.IntProperty(
        name="End",
        description="End frame for motion path",
        default=250,
        min=1
    )
    icosphere_radius: bpy.props.FloatProperty(
        name="Radius",
        description="Radius of the icosphere",
        default=0.2,
        min=0.001,
        max=1.0
    )
    icosphere_color: bpy.props.FloatVectorProperty(
        name="Icosphere Color",
        description="Color",
        default=(1.0, 0, 0.6),  # Default white color
        min=0.0,
        max=1.0,
        subtype='COLOR'
    )

def update_icospheres(scene):
    settings = scene.motion_path_settings
    for obj in scene.objects:
        if "motion_path_addon_sphere" in obj and obj["motion_path_addon_sphere"]:
            # Assuming the original scale corresponds to the original radius of 0.01
            scale_factor = settings.icosphere_radius
            obj.scale = (scale_factor, scale_factor, scale_factor)

# Register the handler
bpy.app.handlers.depsgraph_update_post.append(update_icospheres)
    
def set_viewport_shading_to_object_color():
    for area in bpy.context.screen.areas: 
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type = 'SOLID'
                    space.shading.color_type = 'OBJECT'
                    break    

def get_frame_range(context):
    settings = context.scene.motion_path_settings
    if settings.use_timeline:
        return context.scene.frame_start, context.scene.frame_end
    else:
        return settings.start_frame, settings.end_frame

def create_base_icosphere(radius, color):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.2, location=(0, 0, 0))
    base_sphere = bpy.context.object
    base_sphere.name = 'BaseIcoSphere'
    base_sphere["motion_path_addon_sphere"] = True
    base_sphere.hide_render = True

    # Set the viewport display color
    rgba_color = (color[0], color[1], color[2], 1.0)
    base_sphere.color = rgba_color

    # Set shading to smooth
    bpy.context.view_layer.objects.active = base_sphere
    bpy.ops.object.shade_smooth()

    return base_sphere


def calculate_geometric_center(obj):
    local_vertices = [vertex.co for vertex in obj.data.vertices]
    n = len(local_vertices)
    mean = sum(local_vertices, Vector()) / n
    return obj.matrix_world @ mean

def create_motion_path(obj, start_frame, end_frame, world_matrix, is_vertex=False, is_bone=False, is_empty=False):
    settings = bpy.context.scene.motion_path_settings
    base_sphere = create_base_icosphere(settings.icosphere_radius, settings.icosphere_color)

    curve_data = bpy.data.curves.new('motion_path_curve', type='CURVE')
    curve_data.dimensions = '3D'
    curve_data.resolution_u = 2

    curve_object = bpy.data.objects.new('motion_path', curve_data)
    bpy.context.scene.collection.objects.link(curve_object)
    curve_object['is_motion_path'] = True

    polyline = curve_data.splines.new('POLY')
    polyline.points.add(end_frame - start_frame)

    for frame in range(start_frame, end_frame + 1):
        bpy.context.scene.frame_set(frame)
        if is_empty:
            position = obj.matrix_world.translation
        elif is_vertex:
            # For vertices, ensure obj is a mesh type
            if obj.type == 'MESH':
                position = world_matrix @ obj.data.vertices[is_vertex].co
            else:
                continue  # Skip if obj is not a mesh
        elif is_bone:
            # For bones, ensure obj is an armature
            if obj.type == 'ARMATURE':
                bone = obj.pose.bones[is_bone]
                position = world_matrix @ bone.head  # Use head or tail as needed
            else:
                continue  # Skip if obj is not an armature
        else:  # General object
            position = obj.matrix_world.translation

        polyline.points[frame - start_frame].co = (position[0], position[1], position[2], 1)

        sphere_instance = base_sphere.copy()
        sphere_instance.data = base_sphere.data.copy()
        sphere_instance.location = position
        sphere_instance.parent = curve_object
        bpy.context.scene.collection.objects.link(sphere_instance)

    base_sphere.hide_set(True)

class BonePathOperator(bpy.types.Operator):
    bl_idname = "object.bone_path"
    bl_label = "Bone"

    def execute(self, context):
        armature = context.active_object
        bone = context.active_pose_bone
        if armature and armature.type == 'ARMATURE' and bone:
            start_frame, end_frame = get_frame_range(context)
            create_motion_path(armature, start_frame, end_frame, armature.matrix_world, is_bone=bone.name)
            self.report({'INFO'}, "Bone motion path created")
        else:
            self.report({'ERROR'}, "No active bone in selected armature")
        set_viewport_shading_to_object_color()    
        return {'FINISHED'}
    
class VertexPathOperator(bpy.types.Operator):
    bl_idname = "object.vertex_path"
    bl_label = "Vertex"

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type == 'MESH':
            if bpy.ops.object.mode_set.poll():
                bpy.ops.object.mode_set(mode='OBJECT')
            selected_verts = [v for v in obj.data.vertices if v.select]
            if selected_verts:
                start_frame, end_frame = get_frame_range(context)
                # Pass the vertex index directly
                create_motion_path(obj, start_frame, end_frame, obj.matrix_world, is_vertex=selected_verts[0].index)
                if bpy.ops.object.mode_set.poll():
                    bpy.ops.object.mode_set(mode='EDIT')
                self.report({'INFO'}, "Vertex motion path created")
            else:
                self.report({'ERROR'}, "No vertex selected")
        else:
            self.report({'ERROR'}, "No mesh in edit mode selected")
        set_viewport_shading_to_object_color()    
        return {'FINISHED'}
    
class EmptyPathOperator(bpy.types.Operator):
    bl_idname = "object.empty_path"
    bl_label = "Empty"

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type == 'EMPTY':
            start_frame, end_frame = get_frame_range(context)
            create_motion_path(obj, start_frame, end_frame, obj.matrix_world, "location", is_empty=True)
            self.report({'INFO'}, "Empty motion path created")
        else:
            self.report({'ERROR'}, "No empty object selected")
        set_viewport_shading_to_object_color()    
        return {'FINISHED'}


class ObjectPathOperator(bpy.types.Operator):
    bl_idname = "object.object_path"
    bl_label = "Object"

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type in {'MESH', 'CURVE', 'SURFACE', 'FONT'}:  # Add other types as needed
            start_frame, end_frame = get_frame_range(context)
            create_motion_path(obj, start_frame, end_frame, obj.matrix_world)
            self.report({'INFO'}, "Object motion path created")
        else:
            self.report({'ERROR'}, "No suitable object selected")
        set_viewport_shading_to_object_color()    
        return {'FINISHED'}
    
class CleanUpOperator(bpy.types.Operator):
    bl_idname = "object.clean_up_motion_path"
    bl_label = "Clean Up"

    def execute(self, context):
        icospheres_to_delete = set()
        curves_to_delete = set()

        # Collect icospheres and curves
        for obj in bpy.data.objects:
            if "motion_path_addon_sphere" in obj and obj["motion_path_addon_sphere"]:
                icospheres_to_delete.add(obj)
                if obj.parent and 'is_motion_path' in obj.parent:
                    curves_to_delete.add(obj.parent)

        # Delete the icospheres
        for icosphere in icospheres_to_delete:
            bpy.data.objects.remove(icosphere, do_unlink=True)

        # Delete the curves
        for curve in curves_to_delete:
            if curve.name in bpy.data.objects:  # Ensure the curve still exists
                bpy.data.objects.remove(curve, do_unlink=True)

        self.report({'INFO'}, "Motion path curves and addon spheres cleaned up")
        return {'FINISHED'}


class MotionPathPanel(bpy.types.Panel):
    bl_label = "Motion Path Creator"
    bl_idname = "ANIM_PT_motionpath"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Animation'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.motion_path_settings

        layout.prop(settings, "use_timeline")
        if not settings.use_timeline:
            layout.prop(settings, "start_frame")
            layout.prop(settings, "end_frame")
        layout.prop(settings, "icosphere_radius")  # Add radius control to the UI
        layout.prop(settings, "icosphere_color", text="Color")
        layout.operator("object.bone_path")
        layout.operator("object.vertex_path")
        layout.operator("object.empty_path")
        layout.operator("object.object_path")
        layout.operator("object.clean_up_motion_path")

def register():
    bpy.utils.register_class(MotionPathSettings)
    bpy.types.Scene.motion_path_settings = bpy.props.PointerProperty(type=MotionPathSettings)
    bpy.utils.register_class(BonePathOperator)
    bpy.utils.register_class(VertexPathOperator)
    bpy.utils.register_class(ObjectPathOperator)
    bpy.utils.register_class(EmptyPathOperator)
    bpy.utils.register_class(CleanUpOperator)
    bpy.utils.register_class(MotionPathPanel)


def unregister():
    del bpy.types.Scene.motion_path_settings
    bpy.utils.unregister_class(MotionPathSettings)
    bpy.utils.unregister_class(BonePathOperator)
    bpy.utils.unregister_class(VertexPathOperator)
    bpy.utils.unregister_class(ObjectPathOperator)
    bpy.utils.register_class(EmptyPathOperator)
    bpy.utils.unregister_class(CleanUpOperator)
    bpy.utils.unregister_class(MotionPathPanel)
    bpy.utils.unregister_class(UpdateRadiusOperator)

if __name__ == "__main__":
    register()

import math
from visualization_variables import colorTable, vis_scenario_id, vis_dict

from tqdm import tqdm
import numpy as np
import os
import matplotlib.transforms as transforms
from matplotlib.patches import Rectangle
from matplotlib.colors import Normalize
import pickle
import matplotlib.pyplot as plt
import argparse
import json
import copy
from IPython import embed

center_x, center_y = (0, 0)
interested_agent_color = '#ff0000'
other_agent_color = "#48A6DB"
pred_trajs_color_list = ['red', '#ff4d4d', '#ff6666', '#ff8080', '#ff9999','#ffb3b3']
context_map_range_dict = {
    "TYPE_VEHICLE": 60,
    "TYPE_CYCLIST": 40,
    "TYPE_PEDESTRIAN": 30
}

def GetColorViaAgentType(agentType):
    if(agentType == "TYPE_VEHICLE"):
        return "blue"
    elif(agentType == "TYPE_PEDESTRAIN"):
        return "purple"
    elif(agentType == "TYPE_CYCLIST"):
        return "orange"
    else:
        return "blue"
    
def StoreAgentsMotionInformation(output_path, scenario_id, ori_obj_types, ori_obj_ids, ori_obj_trajs_full):
    agentsInfo = {"scenario_id": scenario_id}
    agentsData = []

    st, ed = (0, 11)
    for i in range(ori_obj_trajs_full.shape[0]):
        # [cx, cy, cz, dx, dy, dz, heading, vel_x, vel_y, valid]
        obj_traj = ori_obj_trajs_full[i][st:ed]
        obj_valid = np.bool_(ori_obj_trajs_full[i][st:ed, -1])
        obj_traj_new = obj_traj
        obj_type = ori_obj_types[i]
        obj_id = ori_obj_ids[i]
        position_x = obj_traj_new[:, 0]
        position_y = obj_traj_new[:, 1]
        bbox_yaw = obj_traj_new[:, 6]
        vel_x = obj_traj_new[:, 7]
        vel_y = obj_traj_new[:, 8]

        tempAgent = {}
        tempAgent['Agent_ID'] = obj_id
        tempAgent['Agent_Type'] = obj_type
        tempAgent['Agent_Position_X'] = position_x.tolist()
        tempAgent['Agent_Position_Y'] = position_y.tolist()
        tempAgent['Agent_Velocity_X'] = vel_x.tolist()
        tempAgent['Agent_Velocity_Y'] = vel_y.tolist()
        tempAgent['Agent_Heading_Angle'] = bbox_yaw.tolist()
        tempAgent['Agent_Data_Is_Vaild'] = obj_valid.tolist()

        agentsData.append(tempAgent)
    
    agentsInfo['agentsData'] = agentsData
    # Writing to a JSON file
    with open(output_path + '/' + scenario_id +'.json', 'w') as json_file:
        json.dump(agentsInfo, json_file, indent=4)
        
def generate_batch_polylines_from_map(polylines, point_sampled_interval=1, vector_break_dist_thresh=1.0, num_points_each_polyline=20):
    """
    Args:
        polylines (num_points, 7): [x, y, z, dir_x, dir_y, dir_z, global_type]

    Returns:
        ret_polylines: (num_polylines, num_points_each_polyline, 7)
        ret_polylines_mask: (num_polylines, num_points_each_polyline)
    """
    point_dim = polylines.shape[-1]

    sampled_points = polylines[::point_sampled_interval]
    sampled_points_shift = np.roll(sampled_points, shift=1, axis=0)
    buffer_points = np.concatenate((sampled_points[:, 0:2], sampled_points_shift[:, 0:2]), axis=-1)  # [ed_x, ed_y, st_x, st_y]
    buffer_points[0, 2:4] = buffer_points[0, 0:2]

    break_idxs = (np.linalg.norm(buffer_points[:, 0:2] - buffer_points[:, 2:4], axis=-1) > vector_break_dist_thresh).nonzero()[0]
    polyline_list = np.array_split(sampled_points, break_idxs, axis=0)
    ret_polylines = []
    ret_polylines_mask = []

    def append_single_polyline(new_polyline):
        cur_polyline = np.zeros((num_points_each_polyline, point_dim), dtype=np.float32)
        cur_valid_mask = np.zeros((num_points_each_polyline), dtype=np.int32)
        cur_polyline[: len(new_polyline)] = new_polyline
        cur_valid_mask[: len(new_polyline)] = 1
        ret_polylines.append(cur_polyline)
        ret_polylines_mask.append(cur_valid_mask)

    for k in range(len(polyline_list)):
        if polyline_list[k].__len__() <= 0:
            continue
        for idx in range(0, len(polyline_list[k]), num_points_each_polyline):
            append_single_polyline(polyline_list[k][idx : idx + num_points_each_polyline])

    ret_polylines = np.stack(ret_polylines, axis=0)
    ret_polylines_mask = np.stack(ret_polylines_mask, axis=0)

    return ret_polylines, ret_polylines_mask

def plt_road_edges(road_edges, polylines, ax):
    for edge_idx in road_edges:
        edge_sta = edge_idx['polyline_index'][0]
        edge_end = edge_idx['polyline_index'][1]
        if edge_end - edge_sta == 1:
            continue
        edge_polylines = polylines[edge_sta:edge_end, :2]
        ax.plot(edge_polylines[:, 0], edge_polylines[:, 1], color='black', alpha=1, zorder=2, linewidth=8)

def area_of_irregular_quadrilateral(points):
    """Calculate the area of an irregular quadrilateral given four points."""
    if len(points) != 4:
        return 0

    # Function to calculate the cross product of two vectors
    def cross_product(p1, p2, p3):
        return (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])

    # Split the quadrilateral into two triangles and calculate the area of each
    area1 = abs(cross_product(points[0], points[1], points[2])) / 2.0
    area2 = abs(cross_product(points[2], points[3], points[0])) / 2.0

    # Sum the areas of the two triangles
    return area1 + area2

def plt_crosswalks(crosswalks, polylines, ax):
    for crosswalk in crosswalks:
        cross_sta = crosswalk['polyline_index'][0]
        cross_end = crosswalk['polyline_index'][1]
        if cross_end - cross_sta == 1:
            continue
        crosswalk_area = area_of_irregular_quadrilateral(polylines[cross_sta:cross_end, :2])
        if crosswalk_area > 500:
            continue
        cross_polylines = np.concatenate((polylines[cross_sta:cross_end, :2], polylines[cross_sta:cross_sta+1, :2]))
        ax.fill(cross_polylines[:, 0], cross_polylines[:, 1], color='#E0D9D8', hatch='//', edgecolor='#494949', alpha=0.5, zorder=3) # #ABABAB

def plt_lanes(lanes, polylines, ax):
    lane_head_width = 1
    lane_head_height = 1.4
    closest_lane_length = 0
    selected_lane_ids = []
    closest_exit_lanes = []
    for lane in lanes:
        lane_sta = lane['polyline_index'][0]
        lane_end = lane['polyline_index'][1]
        if lane_end - lane_sta == 1:
            continue
        lane_type = lane['type']
        lane_polylines = polylines[lane_sta:lane_end]

        if lane_type != 'TYPE_UNDEFINED':
            ax.plot(lane_polylines[:, 0], lane_polylines[:, 1], color='black', alpha=0.8, zorder=2, linewidth=4)
        else:
            ax.plot(lane_polylines[:, 0], lane_polylines[:, 1], color='gray', alpha=0.6, zorder=2, linewidth=3)
        
        poly_incre_x = lane_polylines[-1, 0] - lane_polylines[-2, 0]
        poly_incre_y = lane_polylines[-1, 1] - lane_polylines[-2, 1]
        ax.arrow(lane_polylines[-1, 0] - poly_incre_x, lane_polylines[-1, 1] - poly_incre_y, poly_incre_x, poly_incre_y, head_width=lane_head_width, head_length=lane_head_height, edgecolor='black', facecolor='white', alpha=1, zorder=6)
    return closest_lane_length, selected_lane_ids, closest_exit_lanes

def plt_road_lines(road_lines, polylines, ax):
    for line in road_lines:
        line_sta = line['polyline_index'][0]
        line_end = line['polyline_index'][1]
        if line_end - line_sta == 1:
            continue
        line_type = line['type']
        line_polylines = polylines[line_sta:line_end]
        if line_type == 'TYPE_SOLID_SINGLE_YELLOW' or line_type == 'TYPE_SOLID_DOUBLE_YELLOW':
            ax.plot(line_polylines[:, 0], line_polylines[:, 1], color='black', alpha=1, zorder=2, linewidth=8)
        # elif line_type == 'TYPE_BROKEN_SINGLE_YELLOW' or line_type == 'TYPE_BROKEN_DOUBLE_YELLOW':
        #     ax.plot(line_polylines[:, 0], line_polylines[:, 1], color='yellow', alpha=1, zorder=2, linewidth=4, linestyle='dashed')
        # elif line_type == 'TYPE_SOLID_SINGLE_YELLOW' or line_type == 'TYPE_SOLID_DOUBLE_YELLOW':
        #     ax.plot(line_polylines[:, 0], line_polylines[:, 1], color='yellow', alpha=1, zorder=2, linewidth=4)
        # else:  # TYPE_UNKNOWN, TYPE_BROKEN_SINGLE_WHITE, TYPE_PASSING_DOUBLE_YELLOW
        #     ax.plot(line_polylines[:, 0], line_polylines[:, 1], color='white', alpha=1, zorder=2, linewidth=4, linestyle='dashed')

def DrawMap(polylines, ori_map_infos, ax):
    road_edges = ori_map_infos['road_edge']
    crosswalks = ori_map_infos['crosswalk']
    lanes = ori_map_infos['lane']
    road_lines = ori_map_infos['road_line']
    stop_signs = ori_map_infos['stop_sign']
    
    plt_road_edges(road_edges, polylines, ax)
    plt_crosswalks(crosswalks, polylines, ax)
    plt_lanes(lanes, polylines, ax)
    plt_road_lines(road_lines, polylines, ax)

def GetBoundary(timestamp):
    if timestamp == 3:
        st, ed = (0, 41)
    elif timestamp == 5:
        st, ed = (0, 61)
    else:
        st, ed = (0, 91)
    return st, ed

def ComputeThreshold(vel_x, vel_y, t):
    vel = math.hypot(vel_x, vel_y)
    if vel <= 1.4:
        a = 0.5
    elif vel >= 11:
        a = 1
    else:
        a = 0.5 + 0.5 * (vel - 1.4) / (11 - 1.4)

    if t == 3:
        threshold_lat, threshold_lon = (1, 2)
    elif t == 5:
        threshold_lat, threshold_lon = (1.8, 3.6)
    else:
        threshold_lat, threshold_lon = (3, 6)

    return threshold_lat * a, threshold_lon * a

def DrawCar(scenario_id, ori_obj_trajs_full, ori_sdc_track_index, track_index_to_predict_list, ori_obj_ids, ori_obj_types, ax):
    st, ed = (0, 11)
    for i in range(ori_obj_trajs_full.shape[0]):
        # [cx, cy, cz, dx, dy, dz, heading, vel_x, vel_y, valid]
        obj_traj = ori_obj_trajs_full[i][st:ed]
        obj_valid = np.bool_(ori_obj_trajs_full[i][st:ed, -1])
        obj_traj_new = obj_traj[obj_valid]
        if(not obj_valid[-1]):
            continue

        position_x = obj_traj_new[:, 0]
        position_y = obj_traj_new[:, 1]
        width = obj_traj_new[:, 3]
        length = obj_traj_new[:, 4]
        bbox_yaw = obj_traj_new[:, 6]
        vel_x = obj_traj_new[:, 7]
        vel_y = obj_traj_new[:, 8]

        color_bbox = "black"
        color = other_agent_color
        # color = GetColorViaAgentType(ori_obj_types[i])
        # if i == ori_sdc_track_index:
        #     color = "green"

        if i in track_index_to_predict_list:
            color = interested_agent_color
            #TODO add numbers to each agent
        # ax.text(position_x[-1], position_y[-1], i, color='black', zorder=20, fontweight="bold")

        w = width[-1]
        h = length[-1]
        theta = bbox_yaw[-1]
        x1, y1 = (position_x + w / 2 * np.cos(theta) + h / 2 * np.sin(theta), position_y + w / 2 * np.sin(theta) - h / 2 * np.cos(theta))
        x2, y2 = (position_x + w / 2 * np.cos(theta) - h / 2 * np.sin(theta), position_y + w / 2 * np.sin(theta) + h / 2 * np.cos(theta))
        x3, y3 = (position_x - w / 2 * np.cos(theta) - h / 2 * np.sin(theta), position_y - w / 2 * np.sin(theta) + h / 2 * np.cos(theta))
        x4, y4 = (position_x - w / 2 * np.cos(theta) + h / 2 * np.sin(theta), position_y - w / 2 * np.sin(theta) - h / 2 * np.cos(theta))

        # x5, y5 = (position_x + (w / 2 - w / 4) * np.cos(theta) + (h / 2) * np.sin(theta), position_y + (w / 2 - w / 4) * np.sin(theta) - (h / 2) * np.cos(theta))
        # x6, y6 = (position_x + (w / 2 - w / 4) * np.cos(theta) - (h / 2) * np.sin(theta), position_y + (w / 2 - w / 4) * np.sin(theta) + (h / 2) * np.cos(theta))

        ax.plot([x1[-1], x2[-1], x3[-1], x4[-1], x1[-1]], [y1[-1], y2[-1], y3[-1], y4[-1], y1[-1]], color=color_bbox, zorder=30, alpha=0.7)
        ax.fill([x1[-1], x2[-1], x3[-1], x4[-1]], [y1[-1], y2[-1], y3[-1], y4[-1]], color=color, zorder=30, alpha=0.7)

        # ax.fill([(x1[-1] + x2[-1]) / 2, x6[-1], x5[-1],], [(y1[-1] + y2[-1]) / 2, y6[-1], y5[-1],], color="black", zorder=10)

def DrawThresholdBox(obj_traj, obj_valid, t, color):
    # idx = 11 + t * 10 - 1
    idx = -1

    if obj_valid[idx]:
        vel_x = obj_traj[idx][7]
        vel_y = obj_traj[idx][8]

        endpoint_x = obj_traj[idx][0]
        endpoint_y = obj_traj[idx][1]

        theta = obj_traj[idx][6]

        threshold_lon, threshold_lat = ComputeThreshold(vel_x, vel_y, t)

        bbox_x_1, bbox_y_1 = (endpoint_x + threshold_lat / 2 * np.cos(theta) + threshold_lon / 2 * np.sin(theta), endpoint_y + threshold_lat / 2 * np.sin(theta) - threshold_lon / 2 * np.cos(theta))
        bbox_x_2, bbox_y_2 = (endpoint_x + threshold_lat / 2 * np.cos(theta) - threshold_lon / 2 * np.sin(theta), endpoint_y + threshold_lat / 2 * np.sin(theta) + threshold_lon / 2 * np.cos(theta))
        bbox_x_3, bbox_y_3 = (endpoint_x - threshold_lat / 2 * np.cos(theta) - threshold_lon / 2 * np.sin(theta), endpoint_y - threshold_lat / 2 * np.sin(theta) + threshold_lon / 2 * np.cos(theta))
        bbox_x_4, bbox_y_4 = (endpoint_x - threshold_lat / 2 * np.cos(theta) + threshold_lon / 2 * np.sin(theta), endpoint_y - threshold_lat / 2 * np.sin(theta) - threshold_lon / 2 * np.cos(theta))

        ax.plot([bbox_x_1, bbox_x_2, bbox_x_3, bbox_x_4, bbox_x_1], [bbox_y_1, bbox_y_2, bbox_y_3, bbox_y_4, bbox_y_1], color=color, zorder=100, alpha=1)

def DrawGroundTruth(ori_obj_trajs_full, timeStamp, ori_sdc_track_index, track_index_to_predict_list, ori_obj_ids, ax):
    st, ed = GetBoundary(timeStamp)
    for i in range(ori_obj_trajs_full.shape[0]):
        # [cx, cy, cz, dx, dy, dz, heading, vel_x, vel_y, valid]
        obj_traj = ori_obj_trajs_full[i][st:ed]
        obj_valid = np.bool_(ori_obj_trajs_full[i][st:ed, -1])
        # keep align with DrawCar
        if not np.bool_(ori_obj_trajs_full[i][0:11, -1])[-1]:
            continue
        obj_traj_new = obj_traj[obj_valid]

        position_x = obj_traj_new[:, 0]
        position_y = obj_traj_new[:, 1]
        width = obj_traj_new[:, 3]
        length = obj_traj_new[:, 4]
        bbox_yaw = obj_traj_new[:, 6]
        vel_x = obj_traj_new[:, 7]
        vel_y = obj_traj_new[:, 8]

        color = other_agent_color

        # if i == ori_sdc_track_index:
        #     color = "green"

        if i in track_index_to_predict_list:
            color = interested_agent_color
            # ax.plot(position_x, position_y, color=color, linewidth=10, zorder=20)
            # ax.scatter(position_x[-1], position_y[-1], color=color, marker="*", s=2000, zorder=150, edgecolors="black", alpha=0.5)
        #     color = list(colorTable.values())[ori_obj_ids[i] % len(colorTable)]
        #     DrawThresholdBox(obj_traj, obj_valid, timeStamp, color)
        else:
            ax.plot(position_x, position_y, color=color, linewidth=3, zorder=20)
        # ax.scatter(position_x[-1], position_y[-1], color=color, marker="*", s=200, zorder=11)

        # if(timeStamp == 8 and obj_valid[-1] == False and i in ori_tracks_to_predict_track_index):
        #     ax.scatter(position_x[-1], position_y[-1], color=color, marker="*", s=200, zorder=11)

def DrawPredictTrajectories(all_predicted_traj, timeStamp, ax):
    st, ed = GetBoundary(timeStamp)
    for predicted_traj in all_predicted_traj:
        pred_trajs = predicted_traj["pred_trajs"]
        pred_scores = predicted_traj["pred_scores"]
        object_id = predicted_traj["object_id"]
        object_type = predicted_traj["object_type"]
        gt_trajs = predicted_traj["gt_trajs"]
        track_index_to_predict = predicted_traj["track_index_to_predict"]

        traj_valid = np.bool_(gt_trajs[:, -1])
        color_list = pred_trajs_color_list
        # for pred_traj in pred_trajs:
        for i in range(len(color_list) - 1, -1, -1):
            color = color_list[i]
            pred_score = pred_scores[i]
            pred_traj = pred_trajs[i]

            pred_traj_x = gt_trajs[:, 0][:11]
            pred_traj_x = np.concatenate((pred_traj_x, pred_traj[:, 0]), axis=0)
            # pred_traj_x.extend(list(pred_traj[:, 0]))

            pred_traj_y = gt_trajs[:, 1][:11]
            pred_traj_y = np.concatenate((pred_traj_y, pred_traj[:, 1]), axis=0)
            # pred_traj_y.extend(list(pred_traj[:, 1]))

            pred_traj_x = list(pred_traj_x[st:ed][traj_valid[st:ed]])
            pred_traj_y = list(pred_traj_y[st:ed][traj_valid[st:ed]])

            ax.plot(pred_traj_x, pred_traj_y, color=color, linewidth=20, alpha=0.8, zorder=20)

            ax.scatter(pred_traj_x[-1], pred_traj_y[-1], color=color, marker=".", s=2000, zorder=20, alpha=1)

def DrawPictures(ori_obj_trajs_full, predicted_traj, timeStamp, ori_sdc_track_index, track_index_to_predict_list, ori_obj_ids, ax):
    DrawGroundTruth(ori_obj_trajs_full, timeStamp, ori_sdc_track_index, track_index_to_predict_list, ori_obj_ids, ax)
    DrawPredictTrajectories(predicted_traj, timeStamp, ax)

def rotate_whole_scene_by_track_index(polylines, ori_obj_trajs_full, all_predicted_traj, track_index_to_predict):
    # convert golbal coordinate to local coordinate
    local_obj_point = ori_obj_trajs_full[track_index_to_predict, 10].copy()
    assert local_obj_point[-1] == 1, "the interested agent is invalid at frame 11"
    local_x = local_obj_point[0]
    local_y = local_obj_point[1]
    local_angle = local_obj_point[6]
    rotate_angle = math.pi / 2 - local_angle
    cos_theta = math.cos(rotate_angle)
    sin_theta = math.sin(rotate_angle)
    
    polylines -= local_obj_point[:2]
    polylines = np.stack((polylines[:,0] * cos_theta - polylines[:,1] * sin_theta, polylines[:,0] * sin_theta + polylines[:,1] *cos_theta), axis=1)
    
    ori_obj_trajs_full[:, :, :2] -= local_obj_point[:2]
    ori_obj_trajs_full[:, :, :2] = np.stack((ori_obj_trajs_full[:, :, 0] *cos_theta - ori_obj_trajs_full[:, :, 1] * sin_theta, ori_obj_trajs_full[:, :, 0] * sin_theta + ori_obj_trajs_full[:, :, 1] *cos_theta), axis=2)
    ori_obj_trajs_full[:, :, 6] += rotate_angle
    
    # rotate all predicted trajs
    for predicted_traj in all_predicted_traj:
        predicted_traj["pred_trajs"][:, :, :2] -= local_obj_point[:2]
        predicted_traj["gt_trajs"][:, :2] -= local_obj_point[:2]
        
        
        predicted_traj["pred_trajs"] = np.stack((predicted_traj["pred_trajs"][:, :, 0] *cos_theta - predicted_traj["pred_trajs"][:, :, 1] * sin_theta, predicted_traj["pred_trajs"][:, :, 0] * sin_theta + predicted_traj["pred_trajs"][:, :, 1] *cos_theta), axis=2)
        predicted_traj["gt_trajs"][:, :2] = np.stack((predicted_traj["gt_trajs"][:, 0] *cos_theta - predicted_traj["gt_trajs"][:, 1] * sin_theta, predicted_traj["gt_trajs"][:, 0] * sin_theta + predicted_traj["gt_trajs"][:, 1] *cos_theta), axis=1)
        predicted_traj["gt_trajs"][:, 6] -= rotate_angle
    
    return polylines, ori_obj_trajs_full, all_predicted_traj

def vis_frame(all_predicted_trajs, ori_data_path, output_path):
    scenario_id = all_predicted_trajs[0]["scenario_id"]
    ori_data_path = os.path.join(ori_data_path, "sample_" + scenario_id + ".pkl")
    with open(ori_data_path, "rb") as f:
        ori_data = pickle.load(f)

    ori_track_infos = ori_data["track_infos"]
    ori_obj_types = ori_track_infos["object_type"]
    ori_obj_ids = ori_track_infos["object_id"]
    ori_obj_trajs_full = ori_track_infos["trajs"]

    ori_dynamic_map_infos = ori_data["dynamic_map_infos"]
    ori_map_infos = ori_data["map_infos"]
    ori_scenario_id = ori_data["scenario_id"]
    ori_timestamps_seconds = ori_data["timestamps_seconds"]
    ori_current_time_index = ori_data["current_time_index"]
    ori_objects_of_interest = ori_data["objects_of_interest"]
    ori_tracks_to_predict = ori_data["tracks_to_predict"]

    ori_sdc_track_index = ori_data["sdc_track_index"]
    ori_tracks_to_predict_track_index = ori_tracks_to_predict["track_index"]

    # get all the map info
    # set polylines(n, 7)   7: x, y, z, dir_x, dir_y, dir_z, global_type
    polylines = ori_map_infos["all_polylines"][:, :2]

    for plot_index, track_index_to_predict in enumerate(ori_tracks_to_predict_track_index):
        interested_agent_type = ori_obj_types[track_index_to_predict]
        context_map_range = context_map_range_dict[interested_agent_type]
        
        polylines_rotated, ori_obj_trajs_full_rotated, all_predicted_traj_rotated = rotate_whole_scene_by_track_index(copy.deepcopy(polylines), copy.deepcopy(ori_obj_trajs_full), copy.deepcopy(all_predicted_trajs), track_index_to_predict)

        x_max, x_min = polylines_rotated[:, 0].max(), polylines_rotated[:, 0].min()
        y_max, y_min = polylines_rotated[:, 1].max(), polylines_rotated[:, 1].min()
        w_now = x_max - x_min
        h_now = y_max - y_min
        rate_now = h_now / w_now

        # fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(64, 32))
        fig = plt.figure(figsize=(32, 32), dpi=300, facecolor='white')
        # Add a single subplot to the figure
        ax = fig.add_subplot(1, 1, 1)

        # plt.rc('font', size=60)          # controls default text sizes
        # plt.rc('axes', titlesize=70)     # fontsize of the axes title
        # plt.rc('axes', labelsize=60)     # fontsize of the x and y labels
        # plt.rc('xtick', labelsize=50)    # fontsize of the tick labels
        # plt.rc('ytick', labelsize=50)    # fontsize of the tick labels
        # plt.rc('legend', fontsize=60)    # legend fontsize
        # plt.rc('figure', titlesize=80)   # fontsize of the figure title
        
        DrawMap(polylines_rotated, ori_map_infos, ax)
        DrawCar(scenario_id, ori_obj_trajs_full_rotated, ori_sdc_track_index, ori_tracks_to_predict_track_index, ori_obj_ids, ori_obj_types, ax)
        DrawPictures(ori_obj_trajs_full_rotated, all_predicted_traj_rotated, 8, ori_sdc_track_index, ori_tracks_to_predict_track_index, ori_obj_ids, ax)
        
        ax.axis('off')
        ax.set_xlim([-context_map_range, context_map_range])
        ax.set_ylim([-context_map_range, context_map_range])

        fig.savefig(f"{output_path}/{scenario_id}_{track_index_to_predict}_multi_agent.png", bbox_inches="tight")
        plt.close()


    print(f"scenario id is {scenario_id}")

def main():
    # input your validation set directory
    ori_data_path = "./data/waymo/mtr_processed/processed_scenarios_validation"
    # input the result.pkl of your MTR model on validation set
    eval_result_path = "./output/waymo/mtr+100_percent_data/valid_mtr+100_percent/eval/epoch_29/default/result.pkl"
    # set your output directory
    output_path = "./MTR_Vistualization/VisStaticPic"
    
    os.makedirs(output_path, exist_ok=True)
    
    # open llm-augmented-mtr's result
    with open(eval_result_path, "rb") as f:
        data = pickle.load(f)
    scenario_id_list = []
    for item in data:
        for sample in item:
            scenario_id = sample["scenario_id"]
            scenario_id_list.append(int(scenario_id, 16))
            break

    for s_id in tqdm(vis_dict.keys()):
        # find the scenario in mtr's result file
        index_list = np.where(np.array(scenario_id_list) == int(s_id, 16))[0]
        all_predicted_trajs = data[index_list[0]]  

        vis_frame(all_predicted_trajs, ori_data_path, output_path)

if __name__ == "__main__":
    main()

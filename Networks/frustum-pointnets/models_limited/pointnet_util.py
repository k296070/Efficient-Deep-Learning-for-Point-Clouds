""" PointNet++ Layers

Author: Charles R. Qi
Date: November 2017
"""

import os
import sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
sys.path.append(os.path.join(BASE_DIR, 'tf_ops/sampling'))
sys.path.append(os.path.join(BASE_DIR, 'tf_ops/grouping'))
sys.path.append(os.path.join(BASE_DIR, 'tf_ops/3d_interpolation'))
from tf_sampling import farthest_point_sample, gather_point
from tf_grouping import query_ball_point, group_point, knn_point
from tf_interpolate import three_nn, three_interpolate
import tensorflow as tf
import numpy as np
import tf_util

def new_group_point(points, idx):
    # grouped_points = group_point(points, idx) # (batch_size, npoint, nsample, channel)
    # print("grouped_points:", grouped_points.shape)
    # grouping:
    point_cloud_shape = points.get_shape()
    batch_size = point_cloud_shape[0].value
    num_points = point_cloud_shape[1].value
    num_dims = point_cloud_shape[-1].value
    #idx_ = tf.range(batch_size) * num_points
    #idx_ = tf.reshape(idx_, [batch_size, 1, 1])
    points = tf.reshape(points, [-1, num_dims])
    # print("points:", points.shape)
    grouped_points = tf.gather(points, idx)
    
    return grouped_points

def sample_and_group(npoint, radius, nsample, xyz, points, knn=False, use_xyz=True):
    '''
    Input:
        npoint: int32
        radius: float32
        nsample: int32
        xyz: (batch_size, ndataset, 3) TF tensor
        points: (batch_size, ndataset, channel) TF tensor, if None will just use xyz as points
        knn: bool, if True use kNN instead of radius search
        use_xyz: bool, if True concat XYZ with local point features, otherwise just use point features
    Output:
        new_xyz: (batch_size, npoint, 3) TF tensor
        new_points: (batch_size, npoint, nsample, 3+channel) TF tensor
        idx: (batch_size, npoint, nsample) TF tensor, indices of local points as in ndataset points
        grouped_xyz: (batch_size, npoint, nsample, 3) TF tensor, normalized point XYZs
            (subtracted by seed point XYZ) in local regions
        sampled_idx: () TF tensor, idx for sampled points
    '''

    point_cloud_shape = points.get_shape()
    batch_size = point_cloud_shape[0].value
    # sampled_idx = farthest_point_sample(npoint, xyz)
    sampled_idx = tf.random_uniform(shape=(batch_size,npoint),maxval=npoint-1,dtype=tf.int32)

    new_xyz = gather_point(xyz, sampled_idx) # (batch_size, npoint, 3)
    if knn:
        _,idx = knn_point(nsample, xyz, new_xyz)
    else:
        idx, pts_cnt = query_ball_point(radius, nsample, xyz, new_xyz)
    grouped_xyz = group_point(xyz, idx) # (batch_size, npoint, nsample, 3)
    grouped_xyz -= tf.expand_dims(new_xyz, 2) # translation normalization
    if points is not None:
        # grouped_points = group_point(points, idx) # (batch_size, npoint, nsample, channel)
        # print("grouped_points:", grouped_points.shape)
        # grouping:
        grouped_points = new_group_point(points, idx) # (batch_size, npoint, nsample, channel)
        
        print("grouped_points:", grouped_points.shape)
        new_points = grouped_points
    else:
        new_points = grouped_xyz
    
    print("[Group] points:", new_points.shape)
    return new_xyz, new_points, idx, grouped_xyz

def sample_and_group_all(xyz, points, use_xyz=True):
    '''
    Inputs:
        xyz: (batch_size, ndataset, 3) TF tensor
        points: (batch_size, ndataset, channel) TF tensor, if None will just use xyz as points
        use_xyz: bool, if True concat XYZ with local point features, otherwise just use point features
    Outputs:
        new_xyz: (batch_size, 1, 3) as (0,0,0)
        new_points: (batch_size, 1, ndataset, 3+channel) TF tensor
    Note:
        Equivalent to sample_and_group with npoint=1, radius=inf, use (0,0,0) as the centroid
    '''
    batch_size = xyz.get_shape()[0].value
    nsample = xyz.get_shape()[1].value
    new_xyz = tf.constant(np.tile(np.array([0,0,0]).reshape((1,1,3)), (batch_size,1,1)),
                          dtype=tf.float32) # (batch_size, 1, 3)
    idx = tf.constant(np.tile(np.array(range(nsample)).reshape((1,1,nsample)),
                      (batch_size,1,1)), dtype=tf.int32)
    grouped_xyz = tf.reshape(xyz, (batch_size, 1, nsample, 3)) # (batch_size, npoint=1, nsample, 3)
    if points is not None:
        if use_xyz:
            new_points = tf.concat([xyz, points], axis=2) # (batch_size, 16, 259)
        else:
            new_points = points
        new_points = tf.expand_dims(new_points, 1) # (batch_size, 1, 16, 259)
    else:
        new_points = grouped_xyz
    return new_xyz, new_points, idx, grouped_xyz


def pointnet_sa_module(xyz, points, npoint, radius, nsample, mlp, mlp2, group_all, is_training, bn_decay, scope, bn=True, pooling='max', knn=False, use_xyz=True, use_nchw=False):
    ''' 
    new PointNet Set Abstraction (SA) Module
    '''

    data_format = 'NCHW' if use_nchw else 'NHWC'
    with tf.variable_scope(scope) as sc:
        input_points = xyz

        if points is not None:
            #  input_points = points
            
            if use_xyz:
                input_points = tf.concat([input_points, points], axis=-1)
            else:
                input_points = points
            
        # fit for mlp
        input_points = tf.expand_dims(input_points, -2)
        print("[SSG-MLP] input points:",input_points.shape)
        if use_nchw: input_points = tf.transpose(input_points, [0,3,1,2])
        for i, num_out_channel in enumerate(mlp):
            input_points = tf_util.conv2d(input_points, num_out_channel, [1,1],
                                        padding='VALID', stride=[1,1],
                                        bn=bn, is_training=is_training,
                                        scope='conv%d'%(i), bn_decay=bn_decay,
                                        data_format=data_format) 
        if use_nchw: input_points = tf.transpose(input_points, [0,2,3,1])

        # Sample and Grouping
        if group_all:
            nsample = xyz.get_shape()[1].value
            input_points = tf.squeeze(input_points, -2)
            new_xyz, new_points, idx, grouped_xyz = sample_and_group_all(xyz, input_points, False)
            # new_points = tf.transpose(new_points, [0, 2, 1, 3])
        else:
            new_xyz, new_points, idx, grouped_xyz = \
                        sample_and_group(npoint, radius, nsample, xyz, input_points, knn, use_xyz)

        # Pooling in Local Regions
        if pooling=='max':
            new_points = tf.reduce_max(new_points, axis=[2], keep_dims=True, name='maxpool')
        elif pooling=='avg':
            new_points = tf.reduce_mean(new_points, axis=[2], keep_dims=True, name='avgpool')
        elif pooling=='weighted_avg':
            with tf.variable_scope('weighted_avg'):
                dists = tf.norm(grouped_xyz,axis=-1,ord=2,keep_dims=True)
                exp_dists = tf.exp(-dists * 5)
                weights = exp_dists/tf.reduce_sum(exp_dists,axis=2,keep_dims=True) # (batch_size, npoint, nsample, 1)
                new_points *= weights # (batch_size, npoint, nsample, mlp[-1])
                new_points = tf.reduce_sum(new_points, axis=2, keep_dims=True)
        elif pooling=='max_and_avg':
            max_points = tf.reduce_max(new_points, axis=[2], keep_dims=True, name='maxpool')
            avg_points = tf.reduce_mean(new_points, axis=[2], keep_dims=True, name='avgpool')
            new_points = tf.concat([avg_points, max_points], axis=-1)

        # [Optional] Further Processing 
        if mlp2 is not None:
            if use_nchw: new_points = tf.transpose(new_points, [0,3,1,2])
            for i, num_out_channel in enumerate(mlp2):
                new_points = tf_util.conv2d(new_points, num_out_channel, [1,1],
                                            padding='VALID', stride=[1,1],
                                            bn=bn, is_training=is_training,
                                            scope='conv_post_%d'%(i), bn_decay=bn_decay,
                                            data_format=data_format) 
            if use_nchw: new_points = tf.transpose(new_points, [0,2,3,1])

        new_points = tf.squeeze(new_points, [2]) # (batch_size, npoints, mlp2[-1])
        print("[SSG-MLP] output points:",new_points.shape)
        print("[SSG-MLP] output xyz:", new_xyz.shape)
        return new_xyz, new_points, idx

def pointnet_sa_module_bkup(xyz, points, npoint, radius, nsample, mlp, mlp2, group_all, is_training, bn_decay, scope, bn=True, pooling='max', knn=False, use_xyz=True, use_nchw=False):
    ''' PointNet Set Abstraction (SA) Module
        Input:
            xyz: (batch_size, ndataset, 3) TF tensor
            points: (batch_size, ndataset, channel) TF tensor
            npoint: int32 -- #points sampled in farthest point sampling
            radius: float32 -- search radius in local region
            nsample: int32 -- how many points in each local region
            mlp: list of int32 -- output size for MLP on each point
            mlp2: list of int32 -- output size for MLP on each region
            group_all: bool -- group all points into one PC if set true, OVERRIDE
                npoint, radius and nsample settings
            use_xyz: bool, if True concat XYZ with local point features, otherwise just use point features
            use_nchw: bool, if True, use NCHW data format for conv2d, which is usually faster than NHWC format
        Return:
            new_xyz: (batch_size, npoint, 3) TF tensor
            new_points: (batch_size, npoint, mlp[-1] or mlp2[-1]) TF tensor
            idx: (batch_size, npoint, nsample) int32 -- indices for local regions
    '''
    data_format = 'NCHW' if use_nchw else 'NHWC'
    with tf.variable_scope(scope) as sc:
        # Sample and Grouping
        if group_all:
            nsample = xyz.get_shape()[1].value
            new_xyz, new_points, idx, grouped_xyz = sample_and_group_all(xyz, points, use_xyz)
        else:
            new_xyz, new_points, idx, grouped_xyz = \
                    sample_and_group(npoint, radius, nsample, xyz, points, knn, use_xyz)

        # Point Feature Embedding
        if use_nchw: new_points = tf.transpose(new_points, [0,3,1,2])
        for i, num_out_channel in enumerate(mlp):
            new_points = tf_util.conv2d(new_points, num_out_channel, [1,1],
                                        padding='VALID', stride=[1,1],
                                        bn=bn, is_training=is_training,
                                        scope='conv%d'%(i), bn_decay=bn_decay,
                                        data_format=data_format) 
        if use_nchw: new_points = tf.transpose(new_points, [0,2,3,1])

        # Pooling in Local Regions
        if pooling=='max':
            new_points = tf.reduce_max(new_points, axis=[2], keep_dims=True, name='maxpool')
        elif pooling=='avg':
            new_points = tf.reduce_mean(new_points, axis=[2], keep_dims=True, name='avgpool')
        elif pooling=='weighted_avg':
            with tf.variable_scope('weighted_avg'):
                dists = tf.norm(grouped_xyz,axis=-1,ord=2,keep_dims=True)
                exp_dists = tf.exp(-dists * 5)
                weights = exp_dists/tf.reduce_sum(exp_dists,axis=2,keep_dims=True) # (batch_size, npoint, nsample, 1)
                new_points *= weights # (batch_size, npoint, nsample, mlp[-1])
                new_points = tf.reduce_sum(new_points, axis=2, keep_dims=True)
        elif pooling=='max_and_avg':
            max_points = tf.reduce_max(new_points, axis=[2], keep_dims=True, name='maxpool')
            avg_points = tf.reduce_mean(new_points, axis=[2], keep_dims=True, name='avgpool')
            new_points = tf.concat([avg_points, max_points], axis=-1)

        # [Optional] Further Processing 
        if mlp2 is not None:
            if use_nchw: new_points = tf.transpose(new_points, [0,3,1,2])
            for i, num_out_channel in enumerate(mlp2):
                new_points = tf_util.conv2d(new_points, num_out_channel, [1,1],
                                            padding='VALID', stride=[1,1],
                                            bn=bn, is_training=is_training,
                                            scope='conv_post_%d'%(i), bn_decay=bn_decay,
                                            data_format=data_format) 
            if use_nchw: new_points = tf.transpose(new_points, [0,2,3,1])

        new_points = tf.squeeze(new_points, [2]) # (batch_size, npoints, mlp2[-1])
        
        return new_xyz, new_points, idx

def pointnet_sa_module_msg(xyz, points, npoint, radius_list, nsample_list, mlp_list, \
                is_training, bn_decay, scope, bn=True, use_xyz=True, use_nchw=False):
    ''' 
    new pointnet set abstraction (sa) module with multi-scale grouping (msg)
    '''
    data_format = 'NCHW' if use_nchw else 'NHWC'
    with tf.variable_scope(scope) as sc:
        input_points = xyz
        point_cloud_shape = points.get_shape()
        batch_size = point_cloud_shape[0].value
        sampled_idx = tf.random_uniform(shape=(batch_size,npoint),maxval=npoint-1,dtype=tf.int32) 
        # sampled_idx = farthest_point_sample(npoint, xyz)
        new_xyz = gather_point(xyz, sampled_idx)

        sampled_idx = tf.expand_dims(sampled_idx, -1)
        new_points_list = []
        for i in range(len(radius_list)):
            input_points = xyz
            if points is not None:
                if use_xyz:
                    input_points = tf.concat([input_points, points], axis=-1)
                else:
                    input_points = points
            else:
                input_points = xyz

            # fit for mlp
            input_points = tf.expand_dims(input_points, -2)
            print("[MSG-MLP]",input_points.shape, input_points.dtype)
            if use_nchw: input_points = tf.transpose(input_points, [0,3,1,2])
            for j,num_out_channel in enumerate(mlp_list[i]):
                input_points = tf_util.conv2d(input_points, num_out_channel, [1,1],
                                                padding='VALID', stride=[1,1], bn=bn, 
                                                is_training=is_training,
                                                scope='conv%d_%d'%(i,j), bn_decay=bn_decay)
            if use_nchw: input_points = tf.transpose(input_points, [0,2,3,1])

            radius = radius_list[i]
            nsample = nsample_list[i]
            idx, _ = query_ball_point(radius, nsample, xyz, new_xyz)
            
            # recover for grouping
            input_points = tf.squeeze(input_points, -2)
            sampled_points = new_group_point(input_points, sampled_idx)
            new_points = new_group_point(input_points, idx)

            # sampled_points = tf.squeeze(sampled_points, -2)
            # new_points -= sampled_points
            new_points = tf.reduce_max(new_points, axis=[2])
            new_points -= tf.squeeze(sampled_points, -2)
            # print(tf.shape(input_points), tf.shape(new_points))
            # sampled_points = gather_point(input_points, sampled_idx)
            new_points_list.append(new_points)

        new_points_concat = tf.concat(new_points_list, axis=-1)
        print("[MSG-MLP] output:",new_points_concat.shape)
        return new_xyz, new_points_concat

def pointnet_sa_module_msg_bkup(xyz, points, npoint, radius_list, nsample_list,\
                                mlp_list, is_training, bn_decay, scope, bn=True, \
                                use_xyz=True, use_nchw=False):
    ''' pointnet set abstraction (sa) module with multi-scale grouping (msg)
        input:
            xyz: (batch_size, ndataset, 3) tf tensor
            points: (batch_size, ndataset, channel) tf tensor
            npoint: int32 -- #points sampled in farthest point sampling
            radius: list of float32 -- search radius in local region
            nsample: list of int32 -- how many points in each local region
            mlp: list of list of int32 -- output size for mlp on each point
            use_xyz: bool, if true concat xyz with local point features, otherwise just use point features
            use_nchw: bool, if true, use nchw data format for conv2d, which is usually faster than nhwc format
        return:
            new_xyz: (batch_size, npoint, 3) tf tensor
            new_points: (batch_size, npoint, \sum_k{mlp[k][-1]}) tf tensor
    '''
    data_format = 'NCHW' if use_nchw else 'NHWC'
    with tf.variable_scope(scope) as sc:
        new_xyz = gather_point(xyz, farthest_point_sample(npoint, xyz))
        new_points_list = []
        for i in range(len(radius_list)):
            radius = radius_list[i]
            nsample = nsample_list[i]
            idx, pts_cnt = query_ball_point(radius, nsample, xyz, new_xyz)
            grouped_xyz = group_point(xyz, idx)
            grouped_xyz -= tf.tile(tf.expand_dims(new_xyz, 2), [1,1,nsample,1])
            if points is not None:
                grouped_points = group_point(points, idx)
                if use_xyz:
                    grouped_points = tf.concat([grouped_points, grouped_xyz], axis=-1)
            else:
                grouped_points = grouped_xyz
            if use_nchw: grouped_points = tf.transpose(grouped_points, [0,3,1,2])
            for j,num_out_channel in enumerate(mlp_list[i]):
                grouped_points = tf_util.conv2d(grouped_points, num_out_channel, [1,1],
                                                padding='VALID', stride=[1,1], bn=bn,
                                                is_training=is_training,
                                                scope='conv%d_%d'%(i,j), bn_decay=bn_decay)
            if use_nchw: grouped_points = tf.transpose(grouped_points, [0,2,3,1])
            new_points = tf.reduce_max(grouped_points, axis=[2])
            new_points_list.append(new_points)
        new_points_concat = tf.concat(new_points_list, axis=-1)
        return new_xyz, new_points_concat

 
def pointnet_fp_module(xyz1, xyz2, points1, points2, mlp, is_training, bn_decay, scope, bn=True):
    ''' PointNet Feature Propogation (FP) Module
        Input:                                                                                                      
            xyz1: (batch_size, ndataset1, 3) TF tensor                                                              
            xyz2: (batch_size, ndataset2, 3) TF tensor, sparser than xyz1                                           
            points1: (batch_size, ndataset1, nchannel1) TF tensor                                                   
            points2: (batch_size, ndataset2, nchannel2) TF tensor
            mlp: list of int32 -- output size for MLP on each point                                                 
        Return:
            new_points: (batch_size, ndataset1, mlp[-1]) TF tensor
    '''
    with tf.variable_scope(scope) as sc:
        dist, idx = three_nn(xyz1, xyz2)
        dist = tf.maximum(dist, 1e-10)
        norm = tf.reduce_sum((1.0/dist),axis=2,keep_dims=True)
        norm = tf.tile(norm,[1,1,3])
        weight = (1.0/dist) / norm
        interpolated_points = three_interpolate(points2, idx, weight)

        if points1 is not None:
            new_points1 = tf.concat(axis=2, values=[interpolated_points, points1]) # B,ndataset1,nchannel1+nchannel2
        else:
            new_points1 = interpolated_points
        new_points1 = tf.expand_dims(new_points1, 2)
        print("[Pre-FP]:", new_points1.shape)
        for i, num_out_channel in enumerate(mlp):
            new_points1 = tf_util.conv2d(new_points1, num_out_channel, [1,1],
                                         padding='VALID', stride=[1,1],
                                         bn=bn, is_training=is_training,
                                         scope='conv_%d'%(i), bn_decay=bn_decay)
        new_points1 = tf.squeeze(new_points1, [2]) # B,ndataset1,mlp[-1]
        print("[Post-FP]:", new_points1.shape) 
        return new_points1
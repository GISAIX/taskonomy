'''
  Name: extract.py
  Desc: Extract losses.
  Usage:
    python encode_inputs.py /path/to/cfgdir/ --gpu gpu_id
'''
from __future__ import absolute_import, division, print_function

import argparse
import os
import numpy as np
import pdb
import pickle
from   runstats import Statistics
import tensorflow as tf
import tensorflow.contrib.slim as slim
import threading
import time

import init_paths
from   data.load_ops import resize_rescale_image
from   data.load_ops import class_1000_imagenet
from   data.load_ops import class_selected_imagenet
from   data.load_ops import class_places
from   data.task_data_loading import load_and_specify_preprocessors_for_representation_extraction
import general_utils
from   general_utils import RuntimeDeterminedEnviromentVars
import models.architectures as architectures
from   models.sample_models import *
import utils

parser = argparse.ArgumentParser(description='Extract accuracy for a transfer to class 1000 on ImageNet')
parser.add_argument( '--cfg_dir', dest='cfg_dir', help='directory containing config.py file, should include a checkpoint directory' )
parser.set_defaults(cfg_dir="/home/ubuntu/task-taxonomy-331b/experiments")

parser.add_argument('--gpu', dest='gpu_id',
                    help='GPU device id to use [0]',
                    type=int)
parser.add_argument('--nopause', dest='nopause', action='store_true')
parser.set_defaults(nopause=True)

parser.add_argument('--transfer', dest='pretrain_transfer', action='store_true')
parser.set_defaults(pretrain_transfer=False)

parser.add_argument('--transfer-type', dest='pretrain_transfer_type')
parser.set_defaults(pretrain_transfer_type='rep_only_taskonomy')

parser.add_argument('--task', dest='task')

parser.add_argument('--data-split', dest='data_split')
parser.set_defaults(data_split="train" )

parser.add_argument('--out-dir', dest='out_dir')
parser.set_defaults(out_dir="")

parser.add_argument('--out-name', dest='out_name')
parser.set_defaults(out_name="")

parser.add_argument('--print-every', dest='print_every')
parser.set_defaults(print_every="10")

parser.add_argument('--data-use', dest='data_used', type=int)
parser.set_defaults(data_used=50000)

parser.add_argument('--hidden', dest='hidden', type=int)
parser.set_defaults(hidden=128)

parser.add_argument('--layers', dest='layers', type=int)
parser.set_defaults(layers=2)

parser.add_argument('--num-epochs', dest='num_epochs', type=int)
parser.set_defaults(num_epochs=100)

parser.add_argument('--dropout', dest='dropout', type=float)
parser.set_defaults(dropout=0.5)

parser.add_argument('--from-scratch', dest='from_scratch', action='store_true')
parser.set_defaults(from_scratch=False)

parser.add_argument('--train-encoder', dest='train_encoder', action='store_true')
parser.set_defaults(train_encoder=False)

parser.add_argument('--metric-only', dest='metric_only', action='store_true')
parser.set_defaults(metric_only=False)

parser.add_argument('--places-knowledge', dest='add_places_knowledge', action='store_true')
parser.set_defaults(add_places_knowledge=False)

parser.add_argument('--alex', dest='add_alexnet', action='store_true')
parser.set_defaults(add_alexnet=False)

parser.add_argument('--train-mode', dest='train_mode', action='store_true')
# parser.set_defaults(print_every="100")

# TRAIN_MODE =True 
def main( _ ):
    args = parser.parse_args()
    global TRAIN_MODE
    TRAIN_MODE = args.train_mode
    #task_list = ["autoencoder", "colorization","curvature", "denoise", "edge2d", "edge3d", "ego_motion", "fix_pose", "impainting", "jigsaw", "keypoint2d", "keypoint3d", "non_fixated_pose", "point_match", "reshade", "rgb2depth", "rgb2mist", "rgb2sfnorm", "room_layout", "segment25d", "segment2d", "vanishing_point"]
    #single channel for colorization !!!!!!!!!!!!!!!!!!!!!!!!! COME BACK TO THIS !!!!!!!!!!!!!!!!!!!!!!!!!!!
    task_list = [ args.task ]

    # Get available GPUs
    local_device_protos = utils.get_available_devices()
    print( 'Found devices:', [ x.name for x in local_device_protos ] )  
    # set GPU id
    if args.gpu_id:
        print( 'using gpu %d' % args.gpu_id )
        os.environ[ 'CUDA_VISIBLE_DEVICES' ] = str( args.gpu_id )
    else:
        print( 'no gpu specified' )
    
    for task in task_list:
        to_task = 'class_places'
        if args.pretrain_transfer:
            task_dir = os.path.join(args.cfg_dir, args.pretrain_transfer_type, 
                    'DO_NOT_REPLACE_TARGET_DECODER/16k',  "{}__{}__8__unlocked".format(task, to_task))
        else:
            task_dir = os.path.join(args.cfg_dir, 'final', task)
        cfg = utils.load_config( task_dir, nopause=args.nopause )
        
        root_dir = cfg['root_dir']
        split_file = os.path.abspath( os.path.join( root_dir, 'assets/aws_data/train_places_info.pkl') )
        cfg['dataset_dir'] = '/home/ubuntu/place'

        cfg['train_filenames'] = split_file
        cfg['val_filenames'] = split_file
        cfg['test_filenames'] = split_file 

        if 'train_list_of_fileinfos' in cfg:
            if type(cfg['train_representations_file']) is not list:
                split_file_ =  os.path.join(
                                cfg['input_cfg']['log_root'], task,
                                '{task}_train_places_representations.pkl'.format( task=task ))
            else:
                split_file_ = []
                for fname in cfg['train_representations_file']:
                    split_file_.append(fname.replace('val', 'train_places'))
                if args.add_places_knowledge:
                    split_file_.append(os.path.join(
                                    cfg['input_cfg'][0]['log_root'], 'class_places',
                                    'class_places_train_places_representations.pkl'))
                    cfg['representation_dim'] = [16, 16, 8*len(split_file_)]
                if args.add_alexnet:
                    split_file_.append(os.path.join(
                                    cfg['input_cfg'][0]['log_root'], 'alex',
                                    'alex_train_places_representations.pkl'))
                    cfg['representation_dim'] = [16, 16, 8*(len(split_file_) + 1 )]
                
            cfg['train_representations_file'] = split_file_
            cfg['val_representations_file'] = split_file_
            cfg['test_representations_file'] = split_file_


            split_file_ =  os.path.join(root_dir, 'assets/aws_data/train_places.npy')
            cfg['train_list_of_fileinfos'] = split_file_
            cfg['val_list_of_fileinfos'] = split_file_
            cfg['test_list_of_fileinfos'] = split_file_

        # cfg['resize_interpolation_order'] = 0
        # if cfg['model_path'] is None:
            # cfg['model_path'] = os.path.join(cfg['dataset_dir'], "model_log", task, "model.permanent-ckpt") 
        cfg['target_from_filenames'] = class_places
        # Try latest checkpoint by epoch
        cfg['model_path'] = tf.train.latest_checkpoint(
                os.path.join(
                    cfg['log_root'],
                    'logs',
                    'slim-train'
                ))

        # Try latest checkpoint by time
        if cfg['model_path'] is None:
            cfg['model_path'] = tf.train.latest_checkpoint(
                os.path.join(
                    cfg['log_root'],
                    'logs',
                    'slim-train',
                    'time'
                ))      
 
        # Try to get one saved manually
        if cfg['model_path'] is None:  
            cfg['model_path'] = os.path.join(cfg['log_root'], task, "model.permanent-ckpt") 
            # cfg['model_path'] = os.path.join(cfg['log_root'], 'logs', 'slim-train', 'time', "model.ckpt-1350") 

        cfg['randomize'] = False
        cfg['num_epochs'] = args.num_epochs 
        cfg['batch_size'] = 32 #if TRAIN_MODE else 1
        cfg['num_read_threads'] = 30 
        if 'batch_size' in cfg['encoder_kwargs']:
            cfg['encoder_kwargs']['batch_size'] = cfg['batch_size']
        try:
            cfg['target_cfg']['batch_size'] = cfg['batch_size']
        except:
            pass
        try:
            cfg['target_cfg']['encoder_kwargs']['batch_size'] = cfg['batch_size']
        except:
            pass

        loss_dir = args.cfg_dir
        if args.train_encoder:
            cfg['src_encoder_ckpt'] = tf.train.latest_checkpoint(
                    os.path.join(
                        cfg['input_cfg']['log_root'],
                        task,
                        'logs',
                        'slim-train',
                        'time'
                    ))  
            if cfg['src_encoder_ckpt'] is None:  
                cfg['src_encoder_ckpt'] = os.path.join(cfg['input_cfg']['log_root'], task, "model.permanent-ckpt")
            cfg['finetune_encoder_imagenet'] = True 

        if args.metric_only:
            cfg['metric_net_only'] = True
#             cfg['target_cfg']['metric_kwargs'] = {
                # 'hidden_size': args.hidden,
                # 'layer_num': args.layers,
                # 'output_size': 63,
                # 'initial_dropout': True,
                # 'dropout':args.dropout
            # }  
            cfg['target_cfg']['metric_kwargs'] = {
                'hidden_size': args.hidden,
                'layer_num': args.layers,
                'output_size': 63,
                'dropout':args.dropout
            } 
            print(cfg['target_cfg']['metric_kwargs'])
        cfg['data_used'] = args.data_used
#         cfg['weight_decay'] = 1e-3
        # cfg['encoder_kwargs']['weight_decay'] = cfg['weight_decay']
        # cfg['target_cfg']['weight_decay'] = cfg['weight_decay']
        

        # cfg['target_cfg']['metric_kwargs']['weight_decay'] = 0.001

        cfg['initial_learning_rate'] = 1e-3
        cfg['learning_rate_schedule_kwargs' ] = {
            'boundaries': [np.int64(0), np.int64(20000), np.int64(40000)], 
            'values': [cfg['initial_learning_rate'], cfg['initial_learning_rate']/5., cfg['initial_learning_rate']/10.]
        }
        if type(cfg['input_cfg']) is not list:
            cfg['input_cfg']['num_input'] = 1
        #cfg['target_cfg']['metric_kwargs']['output_size'] =  cfg['target_dim']
        run_extract_losses( args, cfg, loss_dir, task )


def run_extract_losses( args, cfg, save_dir, given_task ):
    transfer = (cfg['model_type'] == architectures.TransferNet)
    if transfer:
        get_data_prefetch_threads_init_fn = utils.get_data_prefetch_threads_init_fn_transfer
        setup_input_fn = utils.setup_input_transfer
        if given_task == 'pixels':
            get_data_prefetch_threads_init_fn = utils.get_data_prefetch_threads_init_fn_transfer_imagenet
            setup_input_fn = utils.setup_input_transfer_imagenet
    else:
        setup_input_fn = utils.setup_input
        get_data_prefetch_threads_init_fn = utils.get_data_prefetch_threads_init_fn

    # set up logging
    tf.logging.set_verbosity( tf.logging.ERROR )
    stats = Statistics()
    print_every = int(args.print_every)

    with tf.Graph().as_default() as g:
        # create ops and placeholders
        inputs = setup_input_fn( cfg, is_training=True, use_filename_queue=False )
        #RuntimeDeterminedEnviromentVars.load_dynamic_variables( inputs, cfg )
        #RuntimeDeterminedEnviromentVars.populate_registered_variables()
        max_steps = get_max_steps(inputs[ 'max_steps' ], args.data_split)
        # build model (and losses and train_op)
        model = utils.setup_model( inputs, cfg, is_training=True )

        # set up metrics to evaluate
        names_to_values, names_to_updates = setup_metrics( inputs, model, cfg )
        train_step_fn = model['train_step_fn'] 
        # execute training 
        start_time = time.time()
        utils.print_start_info( cfg, max_steps, is_training=True )

        # start session and restore model
        training_runners = { 'sess': tf.Session(), 'coord': tf.train.Coordinator() }
        try:
            if cfg['model_path'] is None:
                print('Please specify a checkpoint directory')
                return	
            print('Attention, model_path is ', cfg['model_path']) 
            restore_ckpt = not args.from_scratch 
            if restore_ckpt:
                non_encoder_var = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES)  
                adams = []
                for v in tuple(non_encoder_var):
                    if 'Adam' in v.name:
                        non_encoder_var.remove(v)
                        adams.append(v)
                        continue
                    if 'finetune_encoder_imagenet' in cfg:
                        for x in model['model'].encoder_vars:
                            if v.name == x.name:
                                non_encoder_var.remove(v)        
                if not args.metric_only:
                    saver_for_transfer = tf.train.Saver(non_encoder_var)
                #training_runners['sess'].run(saver_for_transfer)
                    saver_for_transfer.restore( training_runners[ 'sess' ], cfg[ 'model_path' ] )
                else:
                    #saver_for_transfer = tf.train.Saver(non_encoder_var)
                    training_runners['sess'].run(tf.variables_initializer(non_encoder_var))
                training_runners[ 'sess' ].run(tf.variables_initializer(adams))
                print('Loading Source Encoder:...')
                if 'finetune_encoder_imagenet' in cfg:
                    model['init_fn'](training_runners[ 'sess' ])
                print('Starting Training:..')
            else:
                init_op = tf.global_variables_initializer()
                training_runners['sess'].run(init_op)
            assign_op = model['global_step'].assign(0)
            training_runners['sess'].run(assign_op) 
            # var = [v for v in tf.global_variables() if 'decoder' in v.name][0]
            # print(training_runners[ 'sess' ].run(var))

            utils.print_start_info( cfg, max_steps, is_training=True )
            data_prefetch_init_fn = get_data_prefetch_threads_init_fn( inputs, cfg, 
                is_training=True, use_filename_queue=False )
            prefetch_threads = threading.Thread(
                target=data_prefetch_init_fn,
                args=( training_runners[ 'sess' ], training_runners[ 'coord' ] ))
            prefetch_threads.start()
            
            # run one example so that we can calculate some statistics about the representations
            start = time.perf_counter()
            saver = tf.train.Saver()
            save_ckpt_name = 'places'
            if args.from_scratch:
                save_ckpt_name = 'places_scratch_{}_{}'.format(args.layers, args.data_used)
            if args.train_encoder:
                save_ckpt_name = 'places_encoder'
            for step in range( max_steps // 2 - 1 ):
            #for step in range(10):
                total_loss, should_stop = train_step_fn(
                        training_runners['sess'], model['train_op'], model['global_step'], train_step_kwargs=model[ 'train_step_kwargs' ])
                # print(data_idx)
                # print(p.mean(), t)
                stats.push(total_loss)

                if step % print_every == 0 and step > 0: 
                    print( 'Step {0} of {1}: ({5}: {2:.3f} || stddev: {3:.3f} :: ({4:.2f} secs/step)'.format( 
                        step, max_steps - 1,
                        stats.mean(), 
                        np.sqrt(stats.variance()),
                        # stats.variance(),
                        (time.perf_counter() - start) / print_every,
                        'Total_loss'
                        ))
                    start = time.perf_counter()
                if step % 3000 == 2999:
                    saver.save(training_runners['sess'], os.path.join(cfg['log_root'], given_task, '{}_{}'.format(save_ckpt_name, step)))

                if training_runners['coord'].should_stop():
                    break

            #print('Heressss')
            saver.save(training_runners['sess'], os.path.join(cfg['log_root'], given_task, save_ckpt_name))
        finally:
            utils.request_data_loading_end( training_runners )
            utils.end_data_loading_and_sess( training_runners )

def setup_metrics( inputs, model, cfg ):
    # predictions = model[ 'model' ].
    # Choose the metrics to compute:
    # names_to_values, names_to_updates = slim.metrics.aggregate_metric_map( {} )
    return  {}, {}


def get_max_steps(original_max_steps, data_split):
    n_images = None
    if data_split == 'train':
        n_images = 129380
    elif data_split == 'val':
        n_images = 50000 
    elif data_split == 'test':
        n_images = 17853
    else: 
        raise NotImplementedError('Unknown data split {}'.format(data_split))
    if original_max_steps != n_images:
        print("Adjusting number of steps from {} -> {}".format(
            max(original_max_steps, n_images),
            min(original_max_steps, n_images)
        ))
    return min(original_max_steps, n_images)


if __name__=='__main__':
    main( '' )


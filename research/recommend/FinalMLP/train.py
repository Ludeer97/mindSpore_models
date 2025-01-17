# Copyright 2022 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""train_criteo."""
import os
import sys
from mindspore import context
from mindspore.context import ParallelMode
from mindspore.communication.management import init, get_rank, get_group_size
from mindspore.train.model import Model
from mindspore.train.callback import ModelCheckpoint, CheckpointConfig, TimeMonitor, EarlyStopping
from mindspore.common import set_seed
from src.final_mlp import ModelBuilder, AUCMetric
from src.dataset import create_dataset, DataType
from src.callback import EvalCallBack, LossCallBack
from src.model_utils.config import config
from src.model_utils.moxing_adapter import moxing_wrapper
from src.model_utils.device_adapter import get_device_num

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
config.do_eval = config.do_eval == 'True'
config.rank_size = get_device_num()

set_seed(1)


def modelarts_pre_process():
    pass


@moxing_wrapper(pre_process=modelarts_pre_process)
def train_model():
    """ train_final """
    if config.rank_size > 1:
        if config.device_target == "Ascend":
            device_id = int(os.getenv('DEVICE_ID'))
            context.set_context(mode=context.GRAPH_MODE, device_target=config.device_target, device_id=device_id)
            context.reset_auto_parallel_context()
            context.set_auto_parallel_context(parallel_mode=ParallelMode.DATA_PARALLEL,
                                              gradients_mean=True,
                                              all_reduce_fusion_config=[9, 11])
            init()
            rank_id = int(os.environ.get('RANK_ID'))
        elif config.device_target == "GPU":
            init()
            context.set_context(mode=context.GRAPH_MODE, enable_graph_kernel=True, device_target=config.device_target)
            context.set_context(graph_kernel_flags="--enable_cluster_ops=MatMul")
            context.reset_auto_parallel_context()
            context.set_auto_parallel_context(device_num=get_group_size(),
                                              parallel_mode=ParallelMode.DATA_PARALLEL,
                                              gradients_mean=True)
            rank_id = get_rank()
        else:
            print("Unsupported device_target ", config.device_target)
            exit()
    else:
        if config.device_target == "Ascend":
            device_id = int(os.getenv('DEVICE_ID'))
            context.set_context(mode=context.GRAPH_MODE, device_target=config.device_target, device_id=device_id)
        elif config.device_target == "GPU":
            context.set_context(mode=context.GRAPH_MODE, enable_graph_kernel=True, device_target=config.device_target)
            context.set_context(graph_kernel_flags="--enable_cluster_ops=MatMul")
        else:
            context.set_context(mode=context.GRAPH_MODE, device_target=config.device_target, enable_graph_kernel=True)
        config.rank_size = None
        rank_id = None

    ds_train = create_dataset(config.dataset_path,
                              train_mode=True,
                              epochs=1,
                              batch_size=config.batch_size,
                              data_type=DataType(config.data_format),
                              rank_size=config.rank_size,
                              rank_id=rank_id)

    steps_size = ds_train.get_dataset_size()

    if config.convert_dtype:
        config.convert_dtype = config.device_target != "CPU"
    model_builder = ModelBuilder(config, config)
    train_net, eval_net = model_builder.get_train_eval_net()
    auc_metric = AUCMetric()
    model = Model(train_net, eval_network=eval_net, metrics={"auc": auc_metric})

    time_callback = TimeMonitor(data_size=ds_train.get_dataset_size())
    loss_callback = LossCallBack(loss_file_path=config.loss_file_name)
    callback_list = [time_callback, loss_callback]

    if config.save_checkpoint:
        if config.rank_size:
            config.ckpt_file_name_prefix += str(get_rank())
            config.ckpt_path = os.path.join(config.ckpt_path, 'ckpt_' + str(get_rank()) + '/')
        if config.device_target != "Ascend":
            config_ck = CheckpointConfig(save_checkpoint_steps=steps_size,
                                         keep_checkpoint_max=config.keep_checkpoint_max)
        else:
            config_ck = CheckpointConfig(save_checkpoint_steps=config.save_checkpoint_steps,
                                         keep_checkpoint_max=config.keep_checkpoint_max)
        if not os.path.exists(config.ckpt_path):
            os.makedirs(config.ckpt_path, exist_ok=True)
        ckpt_cb = ModelCheckpoint(prefix=config.ckpt_file_name_prefix,
                                  directory=config.ckpt_path,
                                  config=config_ck)
        callback_list.append(ckpt_cb)

    if config.get('do_eval', False):
        ds_eval = create_dataset(config.dataset_path, train_mode=False,
                                 epochs=1,
                                 batch_size=config.batch_size,
                                 data_type=DataType(config.data_format))
        eval_callback = EvalCallBack(model, ds_eval, auc_metric,
                                     eval_file_path=config.eval_file_name)
        callback_list.append(eval_callback)

    es_config = config.get('earlystopping', {})
    if es_config:
        callback_list.append(EarlyStopping(**es_config))
    print("callback_list={}".format(callback_list))
    model.train(config.train_epochs, ds_train, callbacks=callback_list, dataset_sink_mode=True)

    is_test = config.get('test', False)
    if is_test:
        import time
        ds_eval = create_dataset(config.dataset_path, train_mode='test',
                                 epochs=1, batch_size=config.batch_size,
                                 data_type=DataType(config.data_format))
        start = time.time()
        res = model.eval(ds_eval)
        eval_time = time.time() - start
        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        out_str = f'infer test_dataset: {time_str} AUC: {list(res.values())[0]}, use time: {eval_time}s.'
        print(out_str)

if __name__ == '__main__':
    train_model()

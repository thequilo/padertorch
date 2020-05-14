import torch
from einops import rearrange
from padertorch import Module
from padertorch.contrib.je.modules.conv import (
    CNN2d, CNN1d, CNNTranspose2d, CNNTranspose1d
)
from padertorch.modules.fully_connected import fully_connected_stack
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence


class HybridCNN(Module):
    """
    Combines CNN2d and CNN1d sequentially.
    """
    def __init__(
            self,
            cnn_2d: CNN2d,
            cnn_1d: CNN1d,
            input_size=None,
            return_pool_indices=False
    ):
        super().__init__()
        assert cnn_2d.return_pool_indices == cnn_1d.return_pool_indices == return_pool_indices, (
            cnn_2d.return_pool_indices, cnn_1d.return_pool_indices, return_pool_indices
        )
        self.cnn_2d = cnn_2d
        self.cnn_1d = cnn_1d
        self.input_size = input_size
        self.return_pool_indices = return_pool_indices

    def forward(self, x, seq_len=None):
        if self.cnn_2d.return_pool_indices:
            x, seq_len, pool_indices_2d = self.cnn_2d(
                x, seq_len
            )
        else:
            x, seq_len = self.cnn_2d(x, seq_len)
            pool_indices_2d = None
        x = rearrange(x, 'b c f t -> b (c f) t')
        if self.cnn_1d.return_pool_indices:
            x, seq_len, pool_indices_1d = self.cnn_1d(
                x, seq_len=seq_len
            )
        else:
            x, seq_len = self.cnn_1d(x, seq_len)
            pool_indices_1d = None
        if self.return_pool_indices:
            return (
                x, seq_len,
                (pool_indices_2d, pool_indices_1d)
            )
        return x, seq_len

    @classmethod
    def finalize_dogmatic_config(cls, config):
        config['cnn_2d'] = {
            'factory': CNN2d,
            'return_pool_indices': config['return_pool_indices']
        }
        config['cnn_1d'] = {
            'factory': CNN1d,
            'return_pool_indices': config['return_pool_indices']
        }
        if config['input_size'] is not None:
            cnn_2d = config['cnn_2d']['factory'].from_config(config['cnn_2d'])
            _, out_channels, output_size, _ = cnn_2d.get_shapes((1, config['cnn_2d']['in_channels'], config['input_size'], 1000))[-1]
            config['cnn_1d']['in_channels'] = out_channels * output_size

    @classmethod
    def get_transpose_config(cls, config, transpose_config=None):
        assert config['factory'] == cls, (config['factory'], cls)
        if transpose_config is None:
            transpose_config = dict()
        transpose_config['factory'] = HybridCNNTranspose
        transpose_config['cnn_transpose_1d'] = config['cnn_1d']['factory'].get_transpose_config(config['cnn_1d'])
        transpose_config['cnn_transpose_2d'] = config['cnn_2d']['factory'].get_transpose_config(config['cnn_2d'])
        return transpose_config

    def get_shapes(self, in_shape):
        cnn_2d_shapes = self.cnn_2d.get_shapes(in_shape)
        out_shape = cnn_2d_shapes[-1]
        cnn_1d_shapes = self.cnn_1d.get_shapes((out_shape[0], out_shape[1]*out_shape[2], out_shape[3]))
        return cnn_2d_shapes, cnn_1d_shapes

    def get_seq_lens(self, in_lengths):
        cnn_2d_lengths = self.cnn_2d.get_seq_lens(in_lengths)
        cnn_1d_lengths = self.cnn_1d.get_seq_lens(cnn_2d_lengths[-1])
        return cnn_2d_lengths, cnn_1d_lengths


class HybridCNNTranspose(Module):
    """
    Combines CNNTranspose1d and CNNTranspose2d sequentially.
    """
    def __init__(
            self,
            cnn_transpose_1d: CNNTranspose1d,
            cnn_transpose_2d: CNNTranspose2d
    ):
        super().__init__()
        self.cnn_transpose_1d = cnn_transpose_1d
        self.cnn_transpose_2d = cnn_transpose_2d

    def forward(
            self, x, seq_len=None,
            shapes=None,
            seq_lens=None,
            pool_indices=None,
    ):
        if shapes is None:
            shapes = (None, None)
        shapes_2d, shapes_1d = shapes
        if seq_lens is None:
            seq_lens = (None, None)
        lengths_2d, lengths_1d = seq_lens
        if pool_indices is None:
            pool_indices = (None, None)
        pool_indices_2d, pool_indices_1d = pool_indices
        x, seq_len = self.cnn_transpose_1d(
            x,
            seq_len=seq_len,
            shapes=shapes_1d,
            seq_lens=lengths_1d,
            pool_indices=pool_indices_1d,
        )
        x = x.view(
            (x.shape[0], self.cnn_transpose_2d.in_channels, -1, x.shape[-1])
        )
        x, seq_len = self.cnn_transpose_2d(
            x,
            seq_len=seq_len,
            shapes=shapes_2d,
            seq_lens=lengths_2d,
            pool_indices=pool_indices_2d,
        )
        return x, seq_len

    @classmethod
    def finalize_dogmatic_config(cls, config):
        config['cnn_transpose_1d']['factory'] = CNNTranspose1d
        config['cnn_transpose_2d']['factory'] = CNNTranspose2d

    @classmethod
    def get_transpose_config(cls, config, transpose_config=None):
        assert config['factory'] == cls
        if transpose_config is None:
            transpose_config = dict()
        transpose_config['factory'] = HybridCNN
        transpose_config['cnn_2d'] = config['cnn_transpose_2d']['factory'].get_transpose_config(config['cnn_transpose_2d'])
        transpose_config['cnn_1d'] = config['cnn_transpose_1d']['factory'].get_transpose_config(config['cnn_transpose_1d'])
        return transpose_config


class CRNN(Module):
    """
    >>> crnn = CRNN.from_config(CRNN.get_config({\
        'input_size': 80,\
        'cnn_2d': {\
            'in_channels': 1,\
            'out_channels': [32, 32, 16],\
            'kernel_size': 3\
        },\
        'cnn_1d': {\
            'out_channels': [32, 32, 16],\
            'kernel_size': 3\
        },\
        'rnn': {'hidden_size': 64},\
        'fcn': {'hidden_size': 32, 'output_size': 10}\
    }))
    >>> crnn(torch.zeros(4, 1, 80, 100))[0].shape
    torch.Size([4, 100, 10])
    """
    def __init__(
            self, cnn_2d: CNN2d, cnn_1d: CNN1d, rnn, fcn, *,
            post_rnn_pooling=None, input_size=None
    ):
        super().__init__()
        self.input_size = input_size
        self._cnn_2d = cnn_2d
        self._cnn_1d = cnn_1d
        self._rnn = rnn
        self._fcn = fcn
        self._post_rnn_pooling = post_rnn_pooling

    def cnn_2d(self, x, seq_len=None):
        if self._cnn_2d is not None:
            x, seq_len = self._cnn_2d(x, seq_len)
        if x.dim() != 3:
            assert x.dim() == 4
            x = rearrange(x, 'b c f t -> b (c f) t')
        return x, seq_len

    def cnn_1d(self, x, seq_len=None):
        if self._cnn_1d is not None:
            x, seq_len = self._cnn_1d(x, seq_len)
        return x, seq_len

    def rnn(self, x, seq_len=None):
        if self._rnn is None:
            x = rearrange(x, 'b f t -> b t f')
        elif isinstance(self._rnn, nn.RNNBase):
            if self._rnn.batch_first:
                x = rearrange(x, 'b f t -> b t f')
            else:
                x = rearrange(x, 'b f t -> t b f')
            if seq_len is not None:
                x = pack_padded_sequence(
                    x, seq_len, batch_first=self._rnn.batch_first
                )
            x, _ = self._rnn(x)
            if seq_len is not None:
                x = pad_packed_sequence(x, batch_first=self._rnn.batch_first)[0]
            if not self._rnn.batch_first:
                x = rearrange(x, 't b f -> b t f')
        else:
            raise NotImplementedError
        return x

    def post_rnn_pooling(self, x, seq_len):
        if self._post_rnn_pooling is not None:
            x, seq_len = self._post_rnn_pooling(x, seq_len)
        return x, seq_len

    def fcn(self, x):
        if self._fcn is not None:
            x = self._fcn(x)
        return x

    def forward(self, x, seq_len=None):
        x, seq_len = self.cnn_2d(x, seq_len)
        x, seq_len = self.cnn_1d(x, seq_len)
        x = self.rnn(x, seq_len=seq_len)
        x, seq_len = self.post_rnn_pooling(x, seq_len)
        y = self.fcn(x)
        return y, seq_len

    input_size_key = 'input_size'

    @classmethod
    def finalize_dogmatic_config(cls, config):
        config['cnn_2d'] = {'factory': CNN2d}
        config['cnn_1d'] = {'factory': CNN1d}
        config['rnn'] = {'factory': nn.GRU}
        config['fcn'] = {'factory': fully_connected_stack}
        input_size = config[cls.input_size_key]
        if config['cnn_2d'] is not None and input_size is not None:
            in_channels = config['cnn_2d']['in_channels']
            cnn_2d = config['cnn_2d']['factory'].from_config(config['cnn_2d'])
            output_size = cnn_2d.get_shapes((1, in_channels, input_size, 1000))[2]
            input_size = cnn_2d.out_channels[-1] * output_size

        if config['cnn_1d'] is not None:
            if input_size is not None:
                config['cnn_1d']['in_channels'] = input_size
            input_size = config['cnn_1d']['out_channels'][-1]

        if config['rnn'] is not None:
            if config['rnn']['factory'] == nn.GRU:
                config['rnn'].update({
                    'num_layers': 1,
                    'bias': True,
                    'batch_first': True,
                    'dropout': 0.,
                    'bidirectional': False
                })

            if input_size is not None:
                config['rnn']['input_size'] = input_size
            input_size = config['rnn']['hidden_size']

        if config['fcn'] is not None:
            config['fcn']['input_size'] = input_size
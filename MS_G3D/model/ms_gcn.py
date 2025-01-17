import sys
sys.path.insert(0, '')
sys.path.append('..')
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np

from graph.tools import k_adjacency, normalize_adjacency_matrix
from model.mlp import MLP
from model.activation import activation_factory


class MultiScale_GraphConv(nn.Module):
    def __init__(self,
                 num_scales,
                 in_channels,
                 out_channels,
                 A_binary,
                 disentangled_agg=True,
                 use_mask=True,
                 dropout=0,
                 activation='relu'):
        super().__init__()
        self.num_scales = num_scales

        if disentangled_agg:
            A_powers = [k_adjacency(A_binary, k, with_self=True)
                        for k in range(num_scales)]
            A_powers = np.concatenate(
                [normalize_adjacency_matrix(g) for g in A_powers])  # normalize每一个矩阵
        else:
            A_powers = [A_binary + np.eye(len(A_binary))
                        for k in range(num_scales)]
            A_powers = [normalize_adjacency_matrix(g) for g in A_powers]
            A_powers = [np.linalg.matrix_power(
                g, k) for k, g in enumerate(A_powers)]
            A_powers = np.concatenate(A_powers)

        self.A_powers = torch.Tensor(A_powers)
        self.use_mask = use_mask
        if use_mask:
            # NOTE: the inclusion of residual mask appears to slow down training noticeably
            self.A_res = nn.init.uniform_(nn.Parameter(
                torch.Tensor(self.A_powers.shape)), -1e-6, 1e-6)
            # 理解为类型转换函数，将一个不可训练的类型Tensor转换成可以训练的类型parameter并将这个parameter绑定到这个module里面
        self.mlp = MLP(in_channels * num_scales,
                       [out_channels], dropout=dropout, activation=activation)

    def forward(self, x):
        N, C, T, V = x.shape
        self.A_powers = self.A_powers.to(x.device)
        A = self.A_powers.to(x.dtype)
        if self.use_mask:
            A = A + self.A_res.to(x.dtype)
        # print(A.shape)
        # print(x.shape)
        # y=torch.matmul(A,x.t())
        support = x@A.t()
        # support = torch.einsum('vu,nctu->nctv', A, x)  # 爱因斯坦求和
        # print(support-x@A.t())
        # print(support.shape)
        support = support.view(N, C, T, self.num_scales, V)
        support = support.permute(0, 3, 1, 2, 4).contiguous().view(
            N, self.num_scales * C, T, V)  # 这是什么高端操作
        # permute : permute its dimensions
        out = self.mlp(support)
        return out


if __name__ == "__main__":
    from graph.ntu_rgb_d import AdjMatrixGraph
    graph = AdjMatrixGraph()
    A_binary = graph.A_binary
    m = MultiScale_GraphConv(
        num_scales=15, in_channels=3, out_channels=64, A_binary=A_binary)
    x = torch.randn(16, 3, 30, 25)
    print(m(x).shape)
    # torch.onnx.export(m, x, 'msgcn.onnx')
    # import onnx
    # omx = onnx.load('msgcn.onnx')
    # from onnx_tf.backend import prepare
    # tfx = prepare(omx)
    # tfx.export_graph('msgcn.pb')

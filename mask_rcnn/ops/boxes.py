
from typing import Tuple
from ops import nms
from ops.box_convert import _box_cxcywh_to_xyxy, _box_xyxy_to_cxcywh, _box_xywh_to_xyxy, _box_xyxy_to_xywh
# import torchvision
# from torchvision.extension import _assert_has_ops
import oneflow as flow
from oneflow import Tensor

# def nms(boxes: Tensor, scores: Tensor, iou_threshold: float) -> Tensor:
#     """
#     Performs non-maximum suppression (NMS) on the boxes according
#     to their intersection-over-union (IoU).
#
#     NMS iteratively removes lower scoring boxes which have an
#     IoU greater than iou_threshold with another (higher scoring)
#     box.
#
#     If multiple boxes have the exact same score and satisfy the IoU
#     criterion with respect to a reference box, the selected box is
#     not guaranteed to be the same between CPU and GPU. This is similar
#     to the behavior of argsort in PyTorch when repeated values are present.
#
#     Args:
#         boxes (Tensor[N, 4])): boxes to perform NMS on. They
#             are expected to be in ``(x1, y1, x2, y2)`` format with ``0 <= x1 < x2`` and
#             ``0 <= y1 < y2``.
#         scores (Tensor[N]): scores for each one of the boxes
#         iou_threshold (float): discards all overlapping boxes with IoU > iou_threshold
#
#     Returns:
#         keep (Tensor): int64 tensor with the indices
#             of the elements that have been kept
#             by NMS, sorted in decreasing order of scores
#     """
#     # _assert_has_ops()
#     # TODO:
#     # replace flow nms
#     return nms(boxes, scores, iou_threshold)


# @torch.jit._script_if_tracing
def batched_nms(
    boxes: Tensor,
    scores: Tensor,
    idxs: Tensor,
    iou_threshold: float,
) -> Tensor:
    """
    Performs non-maximum suppression in a batched fashion.

    Each index value correspond to a category, and NMS
    will not be applied between elements of different categories.

    Args:
        boxes (Tensor[N, 4]): boxes where NMS will be performed. They
            are expected to be in ``(x1, y1, x2, y2)`` format with ``0 <= x1 < x2`` and
            ``0 <= y1 < y2``.
        scores (Tensor[N]): scores for each one of the boxes
        idxs (Tensor[N]): indices of the categories for each one of the boxes.
        iou_threshold (float): discards all overlapping boxes with IoU > iou_threshold

    Returns:
        keep (Tensor): int64 tensor with the indices of
            the elements that have been kept by NMS, sorted
            in decreasing order of scores
    """
    if boxes.numel() == 0:
        return flow.tensor([], dtype=flow.int64, device=boxes.device)
    # strategy: in order to perform NMS independently per class.
    # we add an offset to all the boxes. The offset is dependent
    # only on the class idx, and is large enough so that boxes
    # from different classes do not overlap
    else:
        assert scores.device == flow.device('cuda'), "Only supports tensor on GPU, but get tensor on {}".format(scores.device)
        max_coordinate = boxes.max()
        offsets = idxs.to(device = boxes.device, dtype= boxes.dtype) * (max_coordinate + flow.Tensor(1, device = boxes.device, dtype = boxes.dtype))
        boxes_for_nms = boxes + offsets[:, None]
        assert boxes_for_nms.device == flow.device('cuda'), "Only supports tensor on GPU, but get tensor on {}".format(boxes_for_nms.device)
        # print(boxes_for_nms.device, scores.device, iou_threshold)
        keep = nms(boxes_for_nms, scores, iou_threshold)
        return keep


def remove_small_boxes(boxes: Tensor, min_size: float) -> Tensor:
    """
    Remove boxes which contains at least one side smaller than min_size.

    Args:
        boxes (Tensor[N, 4]): boxes in ``(x1, y1, x2, y2)`` format
            with ``0 <= x1 < x2`` and ``0 <= y1 < y2``.
        min_size (float): minimum size

    Returns:
        keep (Tensor[K]): indices of the boxes that have both sides
            larger than min_size
    """
    ws, hs = boxes[:, 2] - boxes[:, 0], boxes[:, 3] - boxes[:, 1]
    # print("ws", ws, "hs", hs)
    # keep = (ws >= min_size) & (hs >= min_size)
    #TODO: 0-D tensor
    # Check failed: (start) < (stop) (0 vs 0) slice start must be less than stop
    keep = (ws >= min_size).mul(hs >= min_size)
    # print("keep", keep)
    keep = flow.argwhere(keep)
    return keep


def clip_boxes_to_image(boxes: Tensor, size: Tuple[int, int]) -> Tensor:
    """
    Clip boxes so that they lie inside an image of size `size`.

    Args:
        boxes (Tensor[N, 4]): boxes in ``(x1, y1, x2, y2)`` format
            with ``0 <= x1 < x2`` and ``0 <= y1 < y2``.
        size (Tuple[height, width]): size of the image

    Returns:
        clipped_boxes (Tensor[N, 4])
    """
    dim = boxes.dim()
    boxes_x = boxes[..., 0::2]
    boxes_y = boxes[..., 1::2]
    height, width = size

    # if torchvision._is_tracing():
    #     boxes_x = torch.max(boxes_x, torch.tensor(0, dtype=boxes.dtype, device=boxes.device))
    #     boxes_x = torch.min(boxes_x, torch.tensor(width, dtype=boxes.dtype, device=boxes.device))
    #     boxes_y = torch.max(boxes_y, torch.tensor(0, dtype=boxes.dtype, device=boxes.device))
    #     boxes_y = torch.min(boxes_y, torch.tensor(height, dtype=boxes.dtype, device=boxes.device))
    # else:
    boxes_x = boxes_x.clamp(min=0, max=width)
    boxes_y = boxes_y.clamp(min=0, max=height)

    clipped_boxes = flow.stack((boxes_x, boxes_y), dim=dim)
    return clipped_boxes.reshape(*boxes.shape)


def box_convert(boxes: Tensor, in_fmt: str, out_fmt: str) -> Tensor:
    """
    Converts boxes from given in_fmt to out_fmt.
    Supported in_fmt and out_fmt are:

    'xyxy': boxes are represented via corners, x1, y1 being top left and x2, y2 being bottom right.

    'xywh' : boxes are represented via corner, width and height, x1, y2 being top left, w, h being width and height.

    'cxcywh' : boxes are represented via centre, width and height, cx, cy being center of box, w, h
    being width and height.

    Args:
        boxes (Tensor[N, 4]): boxes which will be converted.
        in_fmt (str): Input format of given boxes. Supported formats are ['xyxy', 'xywh', 'cxcywh'].
        out_fmt (str): Output format of given boxes. Supported formats are ['xyxy', 'xywh', 'cxcywh']

    Returns:
        boxes (Tensor[N, 4]): Boxes into converted format.
    """

    allowed_fmts = ("xyxy", "xywh", "cxcywh")
    if in_fmt not in allowed_fmts or out_fmt not in allowed_fmts:
        raise ValueError("Unsupported Bounding Box Conversions for given in_fmt and out_fmt")

    if in_fmt == out_fmt:
        return boxes.clone()

    if in_fmt != 'xyxy' and out_fmt != 'xyxy':
        # convert to xyxy and change in_fmt xyxy
        if in_fmt == "xywh":
            boxes = _box_xywh_to_xyxy(boxes)
        elif in_fmt == "cxcywh":
            boxes = _box_cxcywh_to_xyxy(boxes)
        in_fmt = 'xyxy'

    if in_fmt == "xyxy":
        if out_fmt == "xywh":
            boxes = _box_xyxy_to_xywh(boxes)
        elif out_fmt == "cxcywh":
            boxes = _box_xyxy_to_cxcywh(boxes)
    elif out_fmt == "xyxy":
        if in_fmt == "xywh":
            boxes = _box_xywh_to_xyxy(boxes)
        elif in_fmt == "cxcywh":
            boxes = _box_cxcywh_to_xyxy(boxes)
    return boxes


def _upcast(t: Tensor) -> Tensor:
    # Protects from numerical overflows in multiplications by upcasting to the equivalent higher type
    if t.dtype == flow.float32:
        return t if t.dtype in (flow.float32, flow.float64) else t.float()
    else:
        return t if t.dtype in (flow.int32, flow.int64) else t.int()


def box_area(boxes: Tensor) -> Tensor:
    """
    Computes the area of a set of bounding boxes, which are specified by its
    (x1, y1, x2, y2) coordinates.

    Args:
        boxes (Tensor[N, 4]): boxes for which the area will be computed. They
            are expected to be in (x1, y1, x2, y2) format with
            ``0 <= x1 < x2`` and ``0 <= y1 < y2``.

    Returns:
        area (Tensor[N]): area for each box
    """
    boxes = _upcast(boxes)
    return (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])


# implementation from https://github.com/kuangliu/torchcv/blob/master/torchcv/utils/box.py
# with slight modifications
def _box_inter_union(boxes1: Tensor, boxes2: Tensor) -> Tuple[Tensor, Tensor]:
    area1 = box_area(boxes1)
    area2 = box_area(boxes2)
    # lt = flow.zeros((boxes1.shape[0], boxes2.shape[0], 2), device=boxes1.device, dtype=flow.float32)
    # rb = flow.zeros((boxes1.shape[0], boxes2.shape[0], 2), device=boxes1.device, dtype=flow.float32)
    # tmp = flow.zeros((1, 2), device=boxes1.device, dtype=flow.float32)
    # for i in range(boxes1.shape[0]):
    #     for j in range(boxes2.shape[0]):
    #         tmp = flow.stack([boxes1[i, :2], boxes2[j, :2]],dim=1)
    #         lt[i, j, :] = flow.max(tmp, dim=1)
    #         tmp = flow.stack([boxes1[i, 2:], boxes2[j, 2:]], dim=1)
    #         rb[i, j, :] = flow.max(tmp, dim=1)

    # for i in range(boxes1.shape[0]):
    #     for j in range(boxes2.shape[0]):
    #         tmp = flow.stack([boxes1[i, :2], boxes2[j, :2]], dim=1)
    #         lt[i, j, :] = flow.max(tmp, dim=1)
    #         tmp = flow.stack([boxes1[i, 2:], boxes2[j, 2:]], dim=1)
    #         rb[i, j, :] = flow.max(tmp, dim=1)

    lt = flow.maximum(boxes1[:, None, :2], boxes2[:, :2])  # [N,M,2]
    rb = flow.minimum(boxes1[:, None, 2:], boxes2[:, 2:])  # [N,M,2]


    wh = _upcast(rb - lt).clamp(min=0)  # [N,M,2]
    inter = wh[:, :, 0] * wh[:, :, 1]  # [N,M]

    union = area1[:, None] + area2 - inter

    return inter, union


def box_iou(boxes1: Tensor, boxes2: Tensor) -> Tensor:
    """
    Return intersection-over-union (Jaccard index) of boxes.

    Both sets of boxes are expected to be in ``(x1, y1, x2, y2)`` format with
    ``0 <= x1 < x2`` and ``0 <= y1 < y2``.

    Args:
        boxes1 (Tensor[N, 4])
        boxes2 (Tensor[M, 4])

    Returns:
        iou (Tensor[N, M]): the NxM matrix containing the pairwise IoU values for every element in boxes1 and boxes2
    """
    inter, union = _box_inter_union(boxes1.to(flow.float32), boxes2.to(flow.float32))
    iou = inter / union
    return iou


# Implementation adapted from https://github.com/facebookresearch/detr/blob/master/util/box_ops.py
def generalized_box_iou(boxes1: Tensor, boxes2: Tensor) -> Tensor:
    """
    Return generalized intersection-over-union (Jaccard index) of boxes.

    Both sets of boxes are expected to be in ``(x1, y1, x2, y2)`` format with
    ``0 <= x1 < x2`` and ``0 <= y1 < y2``.

    Args:
        boxes1 (Tensor[N, 4])
        boxes2 (Tensor[M, 4])

    Returns:
        generalized_iou (Tensor[N, M]): the NxM matrix containing the pairwise generalized_IoU values
        for every element in boxes1 and boxes2
    """

    # degenerate boxes gives inf / nan results
    # so do an early check
    assert (boxes1[:, 2:] >= boxes1[:, :2]).all()
    assert (boxes2[:, 2:] >= boxes2[:, :2]).all()

    inter, union = _box_inter_union(boxes1, boxes2)
    iou = inter / union

    lti = flow.min(boxes1[:, None, :2], boxes2[:, :2])
    rbi = flow.max(boxes1[:, None, 2:], boxes2[:, 2:])

    whi = _upcast(rbi - lti).clamp(min=0)  # [N,M,2]
    areai = whi[:, :, 0] * whi[:, :, 1]

    return iou - (areai - union) / areai

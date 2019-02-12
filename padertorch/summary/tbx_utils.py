import torch

__all__ = [
    'mask_to_image',
    'stft_to_image',
]


def mask_to_image(mask, batch_first=False):
    """
        For more details of the output shape, see the tensorboardx docs
    Args:
        mask: Shape (frames, batch [optional], features)
        batch_first: if true mask shape (batch [optional], frames, features]

    Returns: Shape(features, frames)

    """
    images = torch.clamp(mask * 255, 0, 255)
    images = images.type(torch.ByteTensor)
    if images.dim() == 2:
        return images.cpu().numpy().transpose(1, 0)[::-1]
    elif images.dim() == 3:
        if batch_first:
            return images[0].cpu().numpy().transpose(1, 0)[::-1]
        else:
            return images[:, 0].cpu().numpy().transpose(1, 0)[::-1]
    else:
        raise ValueError('Either the signal has ndim 2 or 3',
                         images.shape)


def stft_to_image(signal, batch_first=False):
    """
        For more details of the output shape, see the tensorboardx docs
    Args:
        mask: Shape (frames, batch [optional], features)
        batch_first: if true mask shape (batch [optional], frames, features]

    Returns: Shape(features, frames)

    """
    return spectrogram_to_image(torch.abs(signal), batch_first=batch_first)


def spectrogram_to_image(signal, batch_first=False):
    """
        For more details of the output shape, see the tensorboardx docs
    Args:
        mask: Shape (frames, batch [optional], features)
        batch_first: if true mask shape (batch [optional], frames, features]

    Returns: Shape(features, frames)

    """
    return mask_to_image(signal / torch.max(signal), batch_first=batch_first)

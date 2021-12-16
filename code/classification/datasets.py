import os
import glob

import cv2
import torch
import numpy as np
from PIL import Image

from pathlib import Path
from torch.utils.data import Dataset

img_formats = ['bmp', 'jpg', 'jpeg', 'png', 'tif', 'tiff', 'dng']  # acceptable image suffixes


def create_dataloader(path, img_size, batch_size, workers=8):
    
    dataset = ClassificationDataset(path, img_size, batch_size)

    batch_size = min(batch_size, len(dataset))
    nw = min([os.cpu_count(), batch_size if batch_size > 1 else 0, workers])  # number of workers
    dataloader = InfiniteDataLoader(dataset,
                                    batch_size=batch_size,
                                    num_workers=nw,
                                    pin_memory=True,
                                    collate_fn=ClassificationDataset.collate_fn)  # torch.utils.data.DataLoader()
    return dataloader


class ClassificationDataset(Dataset):
    def __init__(self, path):
        def img2label_paths(img_paths):
            # Define label paths as a function of image paths
            
            sa = os.sep + 'images' + os.sep  # /images/ substrings
            sb = os.sep + 'labels' + os.sep # /labels/ substrings

            return [x.replace(sa, sb, 1).replace(x.split('.')[-1], 'txt') for x in img_paths]

        try:
            f = []  # image files
            for p in path if isinstance(path, list) else [path]:
                p = Path(p)  # os-agnostic
                if p.is_dir():  # dir
                    f += glob.glob(str(p / '**' / '*.*'), recursive=True)
                elif p.is_file():  # file
                    with open(p, 'r') as t:
                        t = t.read().splitlines()
                        parent = str(p.parent) + os.sep
                        f += [x.replace('./', parent) if x.startswith('./') else x for x in t]  # local to global path
                else:
                    raise Exception('%s does not exist' % p)
            self.img_files = sorted([x.replace('/', os.sep) for x in f if x.split('.')[-1].lower() in img_formats])
            assert self.img_files, 'No images found'
        except Exception as e:
            raise Exception('Error loading data from %s: %s' % (path, e))

        self.label_files = img2label_paths(self.img_files)  # labels
        self.objects, self.labels = self.get_objects_labels()

    def __getitem__(self, index):
        # Load image
        img = self.load_image(index)
        label = self.labels[index]

        img = img[:, :, ::-1].transpose(2, 0, 1)  # BGR to RGB, to 3x416x416
        img = np.ascontiguousarray(img)
        
        return torch.from_numpy(img), torch.tensor(label)

    def get_objects_labels(self):
        objects = []
        labels = []

        for img, label in zip(self.img_files, self.label_files):
            try:
                l = []
                im = Image.open(img)
                im.verify()  # PIL verify
                if os.path.isfile(label):
                    with open(label, 'r') as f:
                        for x in f.read().splitlines():
                            l = np.array(x.split(), dtype=np.float32)

                            if len(l) == 0:
                                break

                            objects.append([img, l[1:]])
                            labels.append(l[0])
            except Exception as e:
                print('WARNING: Ignoring corrupted image and/or label %s: %s' % (img, e))

        return objects, labels


    def load_image(self, index):

        path, box = self.objects[index]
        img = cv2.imread(path)  # BGR
        assert img is not None, 'Image Not Found ' + path

        img = crop_image(img, box)

        return img

    @staticmethod
    def collate_fn(batch):
        return tuple(zip(*batch))


def crop_image(image, box):
    h0, w0 = image.shape[:2]
    
    if len(box) == 0:
        return image

    x, y, w, h = box
    ltx = int((x - w/2) * w0)
    lty = int((y - h/2) * h0)
    rbx = int((x + w/2) * w0)
    rby = int((y + h/2) * h0)

    cropped_image = image[lty:rby, ltx:rbx, :]

    return cropped_image


class InfiniteDataLoader(torch.utils.data.dataloader.DataLoader):
    """ Dataloader that reuses workers

    Uses same syntax as vanilla DataLoader
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        object.__setattr__(self, 'batch_sampler', _RepeatSampler(self.batch_sampler))
        self.iterator = super().__iter__()

    def __len__(self):
        return len(self.batch_sampler.sampler)

    def __iter__(self):
        for i in range(len(self)):
            yield next(self.iterator)


class _RepeatSampler(object):
    """ Sampler that repeats forever

    Args:
        sampler (Sampler)
    """

    def __init__(self, sampler):
        self.sampler = sampler

    def __iter__(self):
        while True:
            yield from iter(self.sampler)
"""Defines data loading logic."""

import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
import os
from utils.load_utils import *
from utils.augment import apply_augs
from tqdm import tqdm
import functools
import multiprocessing as mp


class SHREC_DHG_Dataset(Dataset):
    """Dataset wrapper for the experiment."""

    def __init__(self, data_list: np.array, base_dir: str, D: int, T: int, num_classes: int, transform_dict: dict, cache = None):
        
        super().__init__()

        assert num_classes in [14, 28], "Invalid number of classes for SHREC-DHG"

        self.data_list = data_list.astype(int)
        self.base_dir = base_dir
        self.T = T
        self.D = D
        self.num_classes = num_classes
        self.transform_dict = transform_dict
        self.cache = cache

    def __len__(self):
        return self.data_list.shape[0]

    @staticmethod
    def get_image_joint(data_row: np.ndarray, base_dir: str, T: int, D: int, transform_dict: dict):
        num_frames = data_row[6]
        frame_idxs = get_samples(num_frames, T)

        path_identifier = "gesture_{}/finger_{}/subject_{}/essai_{}/".format(*data_row[:4])

        # Loading joint points
        joint_path = os.path.join(
            base_dir, path_identifier, "skeletons_image.txt" if D == 2 else "skeletons_world.txt"
        )
        joint_points = load_joints(joint_path, frame_idxs, T)

        # Loading images
        image_folder_path = os.path.join(base_dir, path_identifier)
        image_sequence = load_image_sequence(image_folder_path, frame_idxs, T, transform_dict)

        return joint_points, image_sequence


    def __getitem__(self, idx):
        """Args:
            idx (int): Index of data item.
        Returns:
            joint_seq (tensor) - A tensor of shape (T, 22*D)
            image_seq (tensor) - A tensor of shape (T, 1, H, W)
            label (int) - Class label of data item
        """

        if self.num_classes == 14: 
            label = self.data_list[idx, 4] - 1
        elif self.num_classes == 28:
            label = self.data_list[idx, 5] - 1

        num_frames = self.data_list[idx, 6]

        if self.cache is not None:
            c_idx = self.data_list[idx, 7]
            joint_points, image_sequence = self.cache["joint"][c_idx], self.cache["image"][c_idx]
        else:
            joint_points, image_sequence = self.get_image_joint(
                self.data_list[idx], self.base_dir, self.T, self.D, self.transform_dict
            )

        if self.transform_dict["aug"] is not None:
            joint_points, image_sequence = apply_augs(joint_points, image_sequence, self.transform_dict["aug"])

        # bring values to 0-1 range & make float32
        joint_points = joint_points.astype(np.float32)
        image_sequence = (image_sequence / 255).astype(np.float32)

        num_frames = joint_points.shape[0]
        
        if num_frames < self.T:
            joint_points = np.pad(joint_points, ((0, self.T - num_frames), (0, 0)), mode='constant')
            image_sequence = np.pad(image_sequence, ((0, self.T - num_frames), (0, 0), (0, 0), (0, 0)), mode="constant")

        return (
            torch.from_numpy(joint_points),
            torch.from_numpy(image_sequence),
            label
        )

        

def init_cache(data_list: np.ndarray, base_dir: str, T: int, D: int, transform_dict: dict, n_cache_workers : int = 4):
    """Loads entire training set into memory for later use."""

    cache = {"joint": [], "image": []}
    
    loader_fn = functools.partial(
        SHREC_DHG_Dataset.get_image_joint,
        base_dir=base_dir,
        T=T,
        D=D,
        transform_dict=transform_dict
    )

    pool = mp.Pool(n_cache_workers)

    for (joint_points, image_sequence) in tqdm(pool.imap(func=loader_fn, iterable=data_list), total=data_list.shape[0]):
        cache["joint"].append(joint_points)
        cache["image"].append(image_sequence)
    
    pool.close()
    pool.join()

    return cache
            

def get_loader(data_list: np.ndarray, config: dict, cache: dict, train: bool = True):
    dataset = SHREC_DHG_Dataset(
        data_list = data_list,
        base_dir = config["data_root"],
        D = config["hparams"]["model"]["D"],
        T = config["hparams"]["model"]["T"],
        num_classes = config["hparams"]["model"]["num_classes"],
        transform_dict = config["hparams"]["transforms"]["train" if train else "eval"],
        cache = cache
    )

    dataloader = DataLoader(
        dataset,
        batch_size = config["hparams"]["batch_size"],
        num_workers = config["exp"]["n_workers"],
        pin_memory = config["exp"]["pin_memory"],
        shuffle = True if train else False
    )

    return dataloader
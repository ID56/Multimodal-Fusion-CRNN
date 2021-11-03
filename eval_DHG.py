from argparse import ArgumentParser
from config_parser import get_config

from utils.trainer import evaluate_stats
from utils.load_DHG import get_loader, init_cache
from utils.misc import seed_everything, count_params, get_model, log

import torch
from torch import nn
import numpy as np
import wandb

import os
import yaml
import random
import time


def training_pipeline(config, cache = None):
    """Initiates and executes all the steps involved with model training.

    Args:
        config (dict) - Dict containing various settings for the training run.
    """

    config["exp"]["save_dir"] = os.path.join(config["exp"]["exp_dir"], config["exp"]["exp_name"])
    os.makedirs(config["exp"]["save_dir"], exist_ok=True)
    
    ######################################
    # save hyperparameters for current run
    ######################################

    config_str = yaml.dump(config)
    print("Using settings:\n", config_str)

    with open(os.path.join(config["exp"]["save_dir"], "settings.txt"), "w+") as f:
        f.write(config_str)
    
    #####################################
    # initialize training items
    #####################################

    # data
    data_list = np.loadtxt(config["data_list_path"], np.int32)
    data_list = np.hstack([data_list, np.arange(len(data_list)).reshape(-1, 1)])

    val_list = data_list[data_list[:, 2] == config["exp"]["val_sub"]]
    valloader = get_loader(val_list, config, cache, train=False)

    # model
    model = get_model(config["hparams"]["model"])
    print(f"Created model with {count_params(model)} parameters.")

    # restore ckpt
    ckpt_path = os.path.join(config["exp"]["save_dir"], "best.pth")
    ckpt = torch.load(ckpt_path, map_location="cpu")
    model.load_state_dict(ckpt["model_state_dict"])
    print("Successfully restored state.")

    model = model.to(config["hparams"]["device"])
    

    #####################################
    # Evaluation Run
    #####################################

    print("Initiating evaluation.")
    stats = evaluate_stats(model, valloader, config["hparams"]["device"])
    log_dict = {
        "fine": stats["fine"],
        "coarse": stats["coarse"]
    }
    log(log_dict, 0, config)
    return stats


def main(args):
    config = get_config(args.conf)

    seed_everything(config["hparams"]["seed"])

    #################################
    # single time caching
    #################################
    
    data_list = np.loadtxt(config["data_list_path"], np.int32)

    cache = None
    if config["exp"]["cache"]:
        cache = init_cache(
            data_list,
            config["data_root"],
            config["hparams"]["model"]["T"],
            config["hparams"]["model"]["D"],
            config["hparams"]["transforms"]["train"],
            config["exp"]["n_cache_workers"]
        )

    #################################
    # leave one out cross validation
    #################################
    
    subjects = np.unique(data_list[:, 2]).tolist()
    all_preds, all_labels = [], []
    for sub in subjects:
        config["exp"]["val_sub"] = sub
        config["exp"]["exp_name"] = f"sub_{sub}"

        if config["exp"]["wandb"]:
            if config["exp"]["wandb_api_key"] is not None:
                with open(config["exp"]["wandb_api_key"], "r") as f:
                    os.environ["WANDB_API_KEY"] = f.read()

            elif os.environ.get("WANDB_API_KEY", False):
                print(f"Found API key from env variable.")

            else:
                wandb.login()
            

            with wandb.init(project=config["exp"]["proj_name"], name=config["exp"]["exp_name"], config=config["hparams"], tags=config["exp"]["tags"], group=config["exp"]["group"]):
                stats = training_pipeline(config, cache)
        
        else:
            stats = training_pipeline(config, cache)
        
        all_preds.append(stats["preds"])
        all_labels.append(stats["labels"])

    all_preds = np.hstack(all_preds).reshape(-1, 1)
    all_labels = np.hstack(all_labels).reshape(-1, 1)
    all_preds_labels = np.hstack([all_preds, all_labels])

    
    np.savetxt(os.path.join(config["exp"]["exp_dir"], "preds_labels.txt"), all_preds_labels)
    


if __name__ == "__main__":
    parser = ArgumentParser("Driver code.")
    parser.add_argument("--conf", type=str, required=True, help="Path to config.yaml file.")
    args = parser.parse_args()

    main(args)
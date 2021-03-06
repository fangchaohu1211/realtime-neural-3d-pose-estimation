import numpy as np
import random
import itertools
import functools
from glob import glob
from collections import namedtuple
import numpy as np
from PIL import Image

from helpers.logger import setup_logger
from helpers.quaternion import Quaternion


class ObjectsDataset(object):
    """A wrapper for the Objects dataset
    """

    classes = ['ape', 'benchvise', 'cam', 'cat', 'duck']
    Triplet = namedtuple('Triplet', ['anchor', 'puller', 'pusher'])
    TripletItem = namedtuple('TripletItem', ['klass', 'path', 'pose', 'image'])

    def __init__(self, dataset_dir):
        """Initializes the ObjectsDataset: Loads the images and their 
        respective poses (i.e. Quaternions)

        Arguments:
            dataset_dir {string} -- location of the dataset folder
        """

        self.mean = np.array([63.96652548, 54.81466454, 48.04923144])[
            np.newaxis, np.newaxis, :]
        self.logger = setup_logger()
        self.channels, self.width, self.height = 3, 64, 64

        with open('{}real/training_split.txt'.format(dataset_dir)) as f:
            training_split = f.readline()
            training_indices = {
                int(idx.strip())
                for idx in training_split.strip().split(',')
            }

        dataset_train = {}
        dataset_test = {}
        dataset_coarse = {}

        for c in ObjectsDataset.classes:
            dataset_train[c] = []
            dataset_test[c] = []
            dataset_coarse[c] = []

            images = glob('/{}/real/{}/*.png'.format(dataset_dir, c))
            all_indices = set(range(len(images)))

            with open('{}real/{}/poses.txt'.format(dataset_dir, c)) as f:
                poses = f.readlines()

            # Training set from "real"
            for idx in training_indices:
                pose = Quaternion(
                    *map(float, poses[2 * idx + 1].strip().split(' ')))
                image = '{}real/{}/real{}.png'.format(dataset_dir, c, idx)

                dataset_train[c].append((image, pose))

            # Testing set from "real"
            for idx in all_indices - training_indices:
                if 2 * idx + 1 > len(poses) - 1:
                    # If the image has no pose, then skip it!
                    continue

                pose = Quaternion(
                    *map(float, poses[2 * idx + 1].strip().split(' ')))
                image = '{}real/{}/real{}.png'.format(dataset_dir, c, idx)

                dataset_test[c].append((image, pose))

            # Training set from "fine"
            images = glob('{}fine/{}/*.png'.format(dataset_dir, c))
            with open('{}fine/{}/poses.txt'.format(dataset_dir, c)) as f:
                poses = f.readlines()

            for idx in range(len(images)):
                pose = Quaternion(
                    *map(float, poses[2 * idx + 1].strip().split(' ')))
                image = '{}fine/{}/fine{}.png'.format(dataset_dir, c, idx)
                dataset_train[c].append((image, pose))

            # Database set from "coarse"
            images = glob('{}coarse/{}/*.png'.format(dataset_dir, c))
            with open('{}coarse/{}/poses.txt'.format(dataset_dir, c)) as f:
                poses = f.readlines()

            for idx in range(len(images)):
                pose = Quaternion(
                    *map(float, poses[2 * idx + 1].strip().split(' ')))
                image = '{}coarse/{}/coarse{}.png'.format(dataset_dir, c, idx)
                dataset_coarse[c].append((image, pose))

        self.dataset_test = dataset_test
        self.dataset_coarse = dataset_coarse
        self.dataset_train = dataset_train
        self.classes = ObjectsDataset.classes

        # generate cache for dataset_train
        self.dataset_train_list = list(itertools.chain.from_iterable([
            itertools.product([c], self.dataset_train[c])
            for c in self.classes
        ]))

        self.dataset_coarse_list = list(itertools.chain.from_iterable([
            itertools.product([c], self.dataset_coarse[c])
            for c in self.classes
        ]))

        self.dataset_test_list = list(itertools.chain.from_iterable([
            itertools.product([c], self.dataset_test[c])
            for c in self.classes
        ]))

    # def save_dataset_coarse_classes(self):
    #     metadata = '/tmp/metadata.tsv'
    #     with open(metadata, 'w') as metadata_file:
    #         for key in self.dataset_coarse.keys():

    #             metadata_file.write('%d\n' % row)

    def get_item(self, dataset_list, idx):
        """Get Coarse Item (i.e. Image)

        Arguments:
            idx {int} -- index of the coarse element

        Returns:
            array -- array of the image
        """

        c, _ = dataset_list[idx]
        item = self.make_triplet(c, _)

        item_image = np.asarray(item.image)

        return item_image - self.mean

    def get_training_triplet(self, idx):
        """Loads one training item (anchor, puller and pusher).

        Arguments:
            pos {tuple} -- (class, index)

        Returns:
            TrainingItem -- (anchor, puller, pusher)
        """

        triplet = self.get_triplets(idx)

        anchor = np.asarray(triplet.anchor.image)
        puller = np.asarray(triplet.puller.image)
        pusher = np.asarray(triplet.pusher.image)

        return {
            'anchor': anchor - self.mean,
            'puller': puller - self.mean,
            'pusher': pusher - self.mean
        }

    def get_triplets(self, idx):
        """Get triplets for training the CNN (i.e. to learn the feature space)

        Arguments:
            idx {int} -- index of the training item

        Returns:
            Triplet -- a triplet of anchor, puller and pusher
        """

        # Anchor
        c, _ = self.dataset_train_list[idx]
        anchor = self.make_triplet(c, _)

        # Puller
        anchor_to_coarse_distances = [
            item[1].distance(anchor.pose)
            for item in self.dataset_coarse[c]
        ]
        puller_idx = np.argmin(anchor_to_coarse_distances)
        puller = self.make_triplet(c, self.dataset_coarse[c][puller_idx])

        # Pusher
        pusher_from_the_same_class = random.randint(0, 1)

        if pusher_from_the_same_class == 1:
            pusher_idx = np.argmax(anchor_to_coarse_distances)
            pusher = self.make_triplet(c, self.dataset_coarse[c][pusher_idx])
        elif pusher_from_the_same_class == 0:
            class_options = list(set(self.classes) - {c})
            different_class = random.choice(class_options)
            pusher = self.make_triplet(
                different_class,
                random.choice(self.dataset_coarse[different_class])
            )

        return ObjectsDataset.Triplet(anchor, puller, pusher)

    def make_triplet(self, c, tpl):
        """Make triplets for the training

        Arguments:
            c {string} -- class name
            tpl {tuple} -- (file_path, quaternion)

        Returns:
            TripletItem -- a triplet item containing image, file path, pose and class
        """

        return ObjectsDataset.TripletItem(
            path=tpl[0],
            pose=tpl[1],
            klass=c,
            image=Image.open(tpl[0])
        )

    def training_length(self):
        return len(self.dataset_train_list)

    def get_anchor(self, c, idx):
        return self.make_triplet(c, self.dataset_train[c][idx])

    def batch_items(self, dataset_list, batch_size, shuffle=True):
        """Coarse items batch generator

        Arguments:
            batch_size {int} -- Batch size to be generated

        Keyword Arguments:
            shuffle {boolean} -- Should shuffle (default: {True})
        """

        total = len(dataset_list)
        indices = list(range(total))

        if shuffle:
            np.random.shuffle(indices)

        for ndx in range(0, total, batch_size):
            batch_indices = indices[ndx:min(ndx + batch_size, total)]

            batch_images = np.zeros(
                (len(batch_indices), self.width, self.height, self.channels))

            # Create the triplets
            for batch_index, dataset_index in enumerate(batch_indices):
                item = self.get_item(dataset_list, dataset_index)
                batch_images[batch_index, :] = item[:]

            yield batch_images

    def batch_training_triplets(self, batch_size, shuffle=True):
        """Training triplets batch generator

        Arguments:
            batch_size {int} -- Batch size to be generated

        Keyword Arguments:
            shuffle {boolean} -- Should shuffle (default: {True})
        """

        total = len(self.dataset_train_list)
        indices = list(range(total))

        if shuffle:
            np.random.shuffle(indices)

        for ndx in range(0, total, batch_size):
            batch_indices = indices[ndx:min(ndx + batch_size, total)]

            batch_triplets = {
                'anchor': np.zeros((len(batch_indices), self.width, self.height, self.channels)),
                'puller': np.zeros((len(batch_indices), self.width, self.height, self.channels)),
                'pusher': np.zeros((len(batch_indices), self.width, self.height, self.channels))
            }

            # Create the triplets
            for batch_index, dataset_index in enumerate(batch_indices):
                triplet = self.get_training_triplet(dataset_index)
                batch_triplets['anchor'][batch_index, :] = triplet['anchor'][:]
                batch_triplets['puller'][batch_index, :] = triplet['puller'][:]
                batch_triplets['pusher'][batch_index, :] = triplet['pusher'][:]

            yield batch_triplets

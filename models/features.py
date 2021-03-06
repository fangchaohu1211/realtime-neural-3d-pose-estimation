import numpy as np
import tensorflow as tf

tf.logging.set_verbosity(tf.logging.INFO)

class Features(object):
    def __init__(self, loss_margin=1e-8, train=True):
        self.loss_margin = loss_margin
        self.optimization_step = 0

        # num_classes = 5
        input_dim = 64
        channels = 3
        hidden_size = 256
        descriptor_size = 16

        graph = {}

        graph['learning_rate'] = tf.placeholder(tf.float32, shape=[])
        graph['regularizer'] = tf.contrib.layers.l2_regularizer(scale=0.1)

        # Input Layer
        graph['input_layer'] = tf.placeholder(tf.float32, shape=[None, input_dim, input_dim, channels], name='Input')

        # Batch Size
        graph['batch_size'] = tf.placeholder(tf.int32, shape=[], name='BatchSize')

        # Convolutional Layer #1
        graph['conv1'] = tf.layers.conv2d(
            name='Conv1',
            inputs=graph['input_layer'],
            filters=16,
            kernel_size=[8, 8],
            kernel_initializer=tf.truncated_normal_initializer(stddev=0.05),
            bias_initializer=tf.zeros_initializer(),
            kernel_regularizer=graph['regularizer'],
            bias_regularizer=graph['regularizer'],
            activation=tf.nn.relu)

        # Pooling Layer #1
        graph['pool1'] = tf.layers.max_pooling2d(inputs=graph['conv1'], pool_size=[2, 2], strides=2, name='Pool1')

        # Convolutional Layer #2 and Pooling Layer #2
        graph['conv2'] = tf.layers.conv2d(
            name='Conv2',
            inputs=graph['pool1'],
            filters=7,
            kernel_size=[5, 5],
            kernel_initializer=tf.truncated_normal_initializer(stddev=0.05),
            bias_initializer=tf.zeros_initializer(),
            kernel_regularizer=graph['regularizer'],
            bias_regularizer=graph['regularizer'],
            activation=tf.nn.relu)
        graph['pool2'] = tf.layers.max_pooling2d(inputs=graph['conv2'], pool_size=[2, 2], strides=2, name='Pool2')

        graph['pool2_flat'] = tf.reshape(graph['pool2'], [-1, 7 * 12 * 12], name='Pool2_Reshape')
        
        graph['fc1'] = tf.layers.dense(
            inputs=graph['pool2_flat'],
            units=hidden_size,
            activation=tf.nn.relu,
            kernel_initializer=tf.truncated_normal_initializer(stddev=0.05),
            bias_initializer=tf.zeros_initializer(),
            kernel_regularizer=graph['regularizer'],
            bias_regularizer=graph['regularizer'],
            name='FC1')
        
        graph['fc2'] = tf.layers.dense(
            inputs=graph['fc1'],
            units=descriptor_size,
            kernel_initializer=tf.truncated_normal_initializer(stddev=0.05),
            bias_initializer=tf.zeros_initializer(),
            kernel_regularizer=graph['regularizer'],
            bias_regularizer=graph['regularizer'],
            name='Features')

        with tf.name_scope('Anchors'):
            graph['anchor_features'] = graph['fc2'][(0 * graph['batch_size']):(1 * graph['batch_size']), :]
        
        with tf.name_scope('Pullers'):
            graph['puller_features'] = graph['fc2'][(1 * graph['batch_size']):(2 * graph['batch_size']), :]
        
        with tf.name_scope('Pushers'):
            graph['pusher_features'] = graph['fc2'][(2 * graph['batch_size']):(3 * graph['batch_size']), :]

        graph['diff_pos'] = tf.subtract(graph['anchor_features'], graph['puller_features'])
        graph['diff_neg'] = tf.subtract(graph['anchor_features'], graph['pusher_features'])

        graph['diff_pos'] = tf.multiply(graph['diff_pos'], graph['diff_pos'])
        graph['diff_neg'] = tf.multiply(graph['diff_neg'], graph['diff_neg'])

        graph['diff_pos'] = tf.reduce_sum(graph['diff_pos'], axis=1, name='DiffPos')
        graph['diff_neg'] = tf.reduce_sum(graph['diff_neg'], axis=1, name='DiffNeg')

        graph['loss_pairs'] = graph['diff_pos']
        
        with tf.name_scope('loss_triplets_ratio'):
            graph['loss_triplets_ratio'] = 1 - tf.divide(
                graph['diff_neg'], 
                tf.add(
                    self.loss_margin,
                    graph['diff_pos']
                )
            )
        
        graph['loss_triplets'] = tf.maximum(
            tf.zeros_like(graph['loss_triplets_ratio']),
            graph['loss_triplets_ratio'],
            name='LossTriplets'
        )

        reg_variables = tf.get_collection(tf.GraphKeys.REGULARIZATION_LOSSES)
        graph['reg_loss'] = tf.contrib.layers.apply_regularization(graph['regularizer'], reg_variables)

        graph['total_loss'] = 1e2 * graph['loss_triplets'] + 1e-4 * graph['loss_pairs'] + graph['reg_loss']

        with tf.name_scope('TotalLoss'):
            # graph['loss'] = tf.reduce_mean(graph['total_loss'])
            graph['loss'] = tf.reduce_sum(graph['total_loss'])

        # Summary Writers for Tensorboard
        tf.summary.scalar('loss', graph['loss'])
        tf.summary.histogram('fc2', graph['fc2'])

        graph['summary'] = tf.summary.merge_all()

        # Optimizer
        if train:
            self.optimizer = tf.train.AdamOptimizer(graph['learning_rate']).minimize(graph['total_loss'])

        self.graph = graph

        # Tensorflow Saver
        self.saver = tf.train.Saver()
    
    def save_model(self, session, path):
        return self.saver.save(session, path)
    
    def load_model(self, session, path):
        return self.saver.restore(session, path)
    
    def prepare_input(self, anchors, pullers, pushers):
        """Prepares input for the graph
        
        Arguments:
            anchors {array} -- a numpy array with all anchors in a batch
            pullers {array} -- a numpy array with all pullers in a batch
            pushers {array} -- a numpy array with all pushers in a batch
        """

        assert all([
            anchors.shape[0] == pullers.shape[0],
            pullers.shape[0] == pushers.shape[0],
        ]), "Anchors, Pullers and Pushers "
        
        N = anchors.shape[0]
        X = np.concatenate((anchors, pullers, pushers), axis=0)

        return X, N
    
    def __call__(self, session, X):
        """Get features given images in X
        
        Arguments:
            session {tf.Session} -- an actual session where the model is loaded
            X {np.array} -- an array of images
        
        Returns:
            np.array -- an array of features
        """

        feats = session.run(self.graph['fc2'], feed_dict={
            self.graph['input_layer']: X
        })

        return feats

    def evaluate_triplet(self, anchors, pullers, pushers, session=None):
        """Generate the features using the forward pass
        
        Arguments:
            anchors {array} -- [batch_size, width, height, channels]
            pullers {array} -- [batch_size, width, height, channels]
            pushers {array} -- [batch_size, width, height, channels]
        
        Returns:
            tuple -- A tuple of features: (
                [batch_size, number_of_features],
                [batch_size, number_of_features],
                [batch_size, number_of_features]
            )
        """
        
        X, N = self.prepare_input(anchors, pullers, pushers)

        if not session:
            session = tf.Session()

        loss = session.run(self.graph['loss'], feed_dict={
            self.graph['input_layer']: X,
            self.graph['batch_size']: N
        })

        if not session:
            session.close()

        return loss
    
    def optimize(self, session, summary_writer, lr, anchors, pullers, pushers):
        """Run a tensorflow optimization step
        
        Arguments:
            session {tf.Session} -- A tensorflow sessions
            optimizer {tf.Optimizer} -- A tensorflow optimizer (initialized w/ learning rate)
            summary_writer {tf.summary.FileWriter} -- A tensorflow summary file writer
            anchors {array} -- a numpy array of anchors
            pullers {array} -- a numpy array of pullers
            pushers {array} -- a numpy array of pushers
        """

        X, N = self.prepare_input(anchors, pullers, pushers)

        self.optimization_step += 1
        
        results, summary = session.run([self.optimizer, self.graph['summary']], feed_dict={
            self.graph['input_layer']: X,
            self.graph['batch_size']: N,
            self.graph['learning_rate']: lr
        })

        summary_writer.add_summary(summary, self.optimization_step)

        return results
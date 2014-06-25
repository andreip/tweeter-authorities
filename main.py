#!/usr/bin/env python

from collections import defaultdict
import math
import pprint
import re
import sys
import time

import matplotlib
matplotlib.use('TkAgg')

import numpy as np
import pylab as pl
from sklearn import cluster
from sklearn.decomposition import PCA
from sklearn import metrics
from sklearn.neighbors import kneighbors_graph
from sklearn.preprocessing import scale

from bson.objectid import ObjectId
import pymongo

from constants import *
from helpers.helpers import similarity_score, iterator_get_next
from helpers.mongo import *
from patch_tweepy import *

auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
auth.set_access_token(ACCESS_TOKEN, ACCESS_TOKEN_SECRET)

api = tweepy.API(auth, parser=tweepy.parsers.JSONParser())

conn = pymongo.MongoClient("mongodb://localhost")
db = conn[DATABASE_NAME]

def get_tweet_type(col, tweet_id):
    cursor = db[col].find({'id': tweet_id})
    if cursor.count() > 0:
        tweet = cursor.next()
    else:
        print 'Fetching tweet id ' + str(tweet_id)
        try:
            tweet = api.get_status(tweet_id)
        except tweepy.error.TweepError as e:
            print e
            return None
        time.sleep(5)
        db[col].update({'id': tweet['id']}, tweet, upsert=True)
    return get_tweet_type_from_text(tweet['text'])

def get_tweet_type_from_text(tweet_text):
    '''Based on the text it can return one of these types:
     - original tweet OT
     - conversational tweet CT
     - repeated tweet RT
    '''
    if re.match('^@\w+.*', tweet_text):
        return TweetType.CT
    if re.match('^RT @\w+:.*', tweet_text):
        return TweetType.RT
    return TweetType.OT

def conversation_started_by_user(col, tweet):
    '''Check if a tweet like "@john how are you man" is
    first started by john first or by the author itself.
    '''
    # If it's not an in reply to conversation, then he just wanted to
    # talk with @username, he started it :).
    if not tweet['in_reply_to_status_id']:
        return True
    # Else it's still a possibility that he replied to a non
    # conversational tweet (!= CT), in which case he yet again
    # started the discussion.
    reply_to_type = get_tweet_type(col, tweet['in_reply_to_status_id'])
    return reply_to_type != TweetType.CT

def get_retweeters(col, screen_name):
    '''Search db for patterns like RT @screen_name: and count
    the number of users.
    '''
    users = db[col].find({'text': {"$regex" : '.*RT @' + screen_name + '.*'}},
                         {'user.screen_name': 1})
    return map(lambda u: u['user']['screen_name'], users)

def get_user_mentions(tweet, tweet_type):
    '''Get accurate mentions by ignoring semantic header.
    * 'RT @user: The awesome news' becomes 'The awesome news'
      because RT @user is added automatically
    * '@google how awesome is your post!' -> removes '@google' from the start
      the '@google' part is added by twitter automatically if you reply
      to the post
    * '@yale, I like how you've been doing lately!'
      this is not a reply to a specific post, it's thus a mention, we
      don't strip @yale from beginning
    '''
    ignore_start_indices = []
    if tweet_type == TweetType.CT and tweet['in_reply_to_status_id']:
        ignore_start_indices.append(0)
    elif tweet_type == TweetType.RT:
        index = "RT @...".index('@')
        ignore_start_indices.append(index)

    result = []
    for user_mention in tweet['entities']['user_mentions']:
        start_index_of_mention = user_mention['indices'][0]
        # Skip the mentions that we want to ignore due to semantic header
        # added by twitter automatically.
        if not start_index_of_mention in ignore_start_indices:
            result.append(user_mention['screen_name'])
    return result

def compute_user_metrics_from_own_tweets(screen_name, col, author_tweets,
                                         user_metrics):
    print 'Compute metrics for', screen_name
    tweets = db[col].find({'user.screen_name': screen_name}).sort('id',
                          pymongo.ASCENDING)
    retweeters, users_mentioned = [], []
    tweets_texts = []
    actual_retweeters = 0

    for tweet in author_tweets:
        tweet_type = get_tweet_type_from_text(tweet['text'])
        # Find out if conversation was started by crt user.
        if tweet_type == TweetType.CT:
            user_metrics[UM.CT1] += 1
            if conversation_started_by_user(col, tweet):
                user_metrics[UM.CT2] += 1
        elif tweet_type == TweetType.OT:
            user_metrics[UM.OT1] += 1
            # Count the number of URLs one shares in his tweets.
            user_metrics[UM.OT2] += len(tweet['entities']['urls'])
            # Count how many hashtags one has used in all the tweets.
            for hashtag in tweet['entities']['hashtags']:
                user_metrics[UM.OT4] += 1

            # Mark the fact that this tweet has been retweeted at least once.
            if tweet['retweet_count'] > 0:
                user_metrics[UM.RT2] += 1

        elif tweet_type == TweetType.RT:
            user_metrics[UM.RT1] += 1

        # For each tweet, check if it's got any mentions of other
        # users.
        users_mentioned += get_user_mentions(tweet, tweet_type)
        # Keep a record of all texts and check their similarity score.
        tweets_texts.append(tweet['text'])
        # Count how many users have retweeted one's tweets.
        actual_retweeters += tweet['retweet_count']

    # Find in db all the authors that retweeted a given user.
    retweeters = get_retweeters(col, screen_name)
    print 'Retweeters found, actual: ', len(retweeters), actual_retweeters
    # Update the number of unique users that retweeted current users's tweets.
    user_metrics[UM.RT3] = len(set(retweeters))
    # Count the nr of users mentioned by the author; and also unique.
    user_metrics[UM.M1] = len(users_mentioned)
    user_metrics[UM.M2] = len(set(users_mentioned))

    # Computing the OT3 score on the author's tweets. See repo
    # paper IdentifyingTopicalAuthoritiesInMicroblogs.pdf for details.
    score = similarity_score(tweets_texts)
    user_metrics[UM.OT3] = score

def compute_user_metrics_from_other_tweets(screen_name, col, user_metrics):
    '''Find tweets that mention the author. We'll search only for those
    present in db, hoping almost every mentioned has been gathered as
    it's related to the topic.
    '''
    # Get all the mentions of the @screen_name user.
    users_mentioning = db[col].find({'text':
        # Don't begin with '@screen_name'.
        {'$regex': '^(?!@' + screen_name + ')' +\
                   # Don't begin with 'RT @screen_name' either.
                   '(?!RT @' + screen_name + ')' +\
                   # Characters follow and then '@screen_name' must follow too.
                   '.+@' + screen_name + '.*'
        }},
        {'user.screen_name': 1}
    )
    users_mentioning = map(lambda u: u['user']['screen_name'], users_mentioning)
    # Exclude own mentions (it may be a user retweets someone who mentioned
    # him.
    users_mentioning = filter(lambda u: u != screen_name, users_mentioning)

    user_metrics[UM.M3] = len(users_mentioning)
    user_metrics[UM.M4] = len(set(users_mentioning))


def compute_user_metrics(screen_name, col):
    metrics = db[metrics_col(col)].find_one({'_id': screen_name})
    if metrics:
        return defaultdict(int, metrics['metrics'])

    user_metrics = defaultdict(int)
    author_tweets = db[col].find({'user.screen_name':  screen_name})
    compute_user_metrics_from_own_tweets(screen_name, col, author_tweets,
                                         user_metrics)
    compute_user_metrics_from_other_tweets(screen_name, col, user_metrics)

    print '[' + screen_name + '] METRICS: ' + str(user_metrics)

    # Store metric in DB.
    db[metrics_col(col)].update({'_id': screen_name},
                                {'_id': screen_name, 'metrics': user_metrics},
                                upsert=True)

    return user_metrics


def compute_user_features(screen_name, col):
    '''Compute the feature list based on some metrics for each author. See
    UF class for details on features (constants specific file).
    '''
    metrics = compute_user_metrics(screen_name, col)
    features = {}

    user_tweet = db[col].find_one({'user.screen_name': screen_name})
    total_tweets = user_tweet['user']['statuses_count']

    features[UF.TS] = metrics[UM.OT1] + metrics[UM.CT1] + metrics[UM.RT1]
    features[UF.TS] /= float(total_tweets)

    features[UF.SS] = 0 if not metrics[UM.OT1]\
                        else metrics[UM.OT1] / float(metrics[UM.OT1] +
                                                     metrics[UM.RT1])

    nCS1 = 0 if not metrics[UM.OT1]\
             else metrics[UM.OT1] / float(metrics[UM.OT1] + metrics[UM.CT1])
    nCS2 = (metrics[UM.CT1] - metrics[UM.CT2]) / float(metrics[UM.CT1] + 1)
    features[UF.nCS] = nCS1 + nCS_LAMBDA * nCS2

    # Avoid doing log(0), so edge case here.
    features[UF.RI] = 0 if not metrics[UM.RT3] \
                        else metrics[UM.RT2] * math.log(metrics[UM.RT3])

    MI1 = 0 if not metrics[UM.M4] else metrics[UM.M3] * math.log(metrics[UM.M4])
    MI2 = 0 if not metrics[UM.M2] else metrics[UM.M1] * math.log(metrics[UM.M2])
    features[UF.MI] = max(MI1 - MI2, 0)

    features[UF.HR] = 0 if not metrics[UM.OT1]\
                        else metrics[UM.OT4] / float(metrics[UM.OT1])

    features[UF.LR] = 0 if not metrics[UM.OT1]\
                        else metrics[UM.OT4] / float(metrics[UM.OT1])

    features[UF.SIM] = 5 if not metrics[UM.OT3]\
                         else -math.log(metrics[UM.OT3])

    print '[' + screen_name + '] FEATURES: ' + str(features)
    return features


def plot_data(data):
    pl.figure(figsize=(14, 9.5))
    pl.title('Plot Users\' Features', size=18)
    pl.scatter(data[:, 0], data[:, 1], s=10)

    x_min, x_max = data[:, 0].min() - 1, data[:, 0].max() + 1
    y_min, y_max = data[:, 1].min() - 1, data[:, 1].max() + 1

    pl.xlim(x_min, x_max)
    pl.ylim(y_min, y_max)
    pl.xticks(())
    pl.yticks(())
    pl.show()


def reduce_and_store_features(data, col):
    # Create a matrix in np format.
    X = np.vstack(map(lambda e: np.array(e['features'].values()),
                      data)).astype(np.float)
    # Now all features can all be scaled appropriately.
    X = scale(X)
    redX = PCA(n_components=2).fit_transform(X)

    # Store reduced features in db {name, points} so we can the
    # find users associated to them.
    data = data.rewind()
    for i, feature in enumerate(data):
        name = feature['_id']
        db[rfeatures_col(col)].update({'_id': name},
                                      {'_id': name,
                                       'rfsx': redX[i][0],
                                       'rfsy': redX[i][1]
                                      },
                                      upsert=True)
    return redX


def plot_features(col):
    '''Features should be present in collection.'''
    # Check if we've already got reduced features computed.
    data = db[rfeatures_col(col)].find()
    if data.count() > 0:
        print 'Plot from existing reduced features.'
        reduced_data = np.vstack(map(lambda x: [x['rfsx'], x['rfsy']], data))
    else:
        print 'Plot from new computing features.'
        data = db[features_col(col)].find()
        reduced_data = reduce_and_store_features(data, col)
    plot_data(reduced_data)


def compute_centers(data, labels):
    '''Compute the centroids of given data based
    on the labels they've been assigned through clustering.

    See test_compute_centers for a working example.

    Params:
        - data must be an array like (numpy) structure of
          features
        - labels must be a simple list
    Returns:
        - a list of centroids, each of the feature's dimention
    '''
    nr_labels = len(set(labels))
    # Feature dimension.
    n = len(data[0])
    centers = [np.array([0 for _ in range(n)], dtype=np.float)
               for _ in range(nr_labels)]
    members_count = [0 for _ in range(nr_labels)]

    for i, label in enumerate(labels):
        centers[label] += data[i,:]
        # Keep a record of how many members to 'label' there are.
        members_count[label] += 1

    for i, center in enumerate(centers):
        if members_count[i]:
            center /= members_count[i]
    return centers

def get_top_members(members, n_top):
    return sorted(members, key=lambda x: np.mean(x[1].values()), reverse=True)[:n_top]


def find_authorities(q, col):
    '''Finds authorities for a given search.'''
    # Get a list of users that we need to consider as potential authorities
    # about the given topic (from collection col).
    print 'Finding authorities for ', q
    names, data, all_features = get_usernames(col), [], []
    for name in names:
        features = compute_user_features(name, col)
        db[features_col(col)].update({'_id': name},
                                     {'_id': name,
                                      'features': features
                                     },
                                     upsert=True)
        data.append(features.values())
        all_features.append(features)
    X = np.vstack(data)
    X = scale(X)

    K = int(math.log(len(X))) + 1
    bandwidth = cluster.estimate_bandwidth(X, quantile=0.1)
    bandwidth1 = cluster.estimate_bandwidth(X, quantile=0.3)
    bandwidth2 = cluster.estimate_bandwidth(X, quantile=0.6)
    bandwidth3 = cluster.estimate_bandwidth(X, quantile=0.9)

    # connectivity matrix for structured Ward
    connectivity = kneighbors_graph(X, n_neighbors=K)
    # make connectivity symmetric
    connectivity = 0.5 * (connectivity + connectivity.T)

    # Compute distances
    #distances = np.exp(-euclidean_distances(X))
    distances = metrics.euclidean_distances(X)

    k_means = cluster.KMeans(n_clusters=K/3)
    k_means1= cluster.KMeans(n_clusters=K/4)
    k_means2= cluster.KMeans(n_clusters=K/5)
    k_means3= cluster.KMeans(n_clusters=K/6)
    mini_kmeans = cluster.MiniBatchKMeans(n_clusters=K/2,n_init=11)
    mini_kmeans2 = cluster.MiniBatchKMeans(n_clusters=K/3,n_init=11)
    mini_kmeans3 = cluster.MiniBatchKMeans(n_clusters=K/4,n_init=11)
    mini_kmeans4 = cluster.MiniBatchKMeans(n_clusters=K/6,n_init=11)
    ms = cluster.MeanShift(bandwidth=bandwidth, bin_seeding=True)
    ms1 = cluster.MeanShift(bandwidth=bandwidth1, bin_seeding=True)
    ms2 = cluster.MeanShift(bandwidth=bandwidth2, bin_seeding=True)
    ms3 = cluster.MeanShift(bandwidth=bandwidth3, bin_seeding=True)
    ward_k = cluster.Ward(n_clusters=K)#, connectivity=connectivity)
    ward_k1 = cluster.Ward(n_clusters=K/2)#, connectivity=connectivity)
    ward_k2= cluster.Ward(n_clusters=K/4)#, connectivity=connectivity)
    ward_k3= cluster.Ward(n_clusters=K/6)#, connectivity=connectivity)
    spectral = cluster.SpectralClustering(n_clusters=K**2,
                                          eigen_solver='arpack')#,
    spectral1= cluster.SpectralClustering(n_clusters=int(math.sqrt(len(X))),
                                          eigen_solver='arpack')#,
    dbscan = cluster.DBSCAN(eps=1)
    dbscan2 = cluster.DBSCAN(eps=2)
    dbscan3 = cluster.DBSCAN(eps=4)
    dbscan4 = cluster.DBSCAN(eps=8)
    affinity_propagation = cluster.AffinityPropagation(damping=.5,
                                                       preference=-200)
    affinity_propagation1= cluster.AffinityPropagation(damping=.65,
                                                       preference=-200)
    affinity_propagation2= cluster.AffinityPropagation(damping=.8,
                                                       preference=-200)
    affinity_propagation3= cluster.AffinityPropagation(damping=.95,
                                                       preference=-200)
    xaffinity_propagation = cluster.AffinityPropagation(damping=.5)
    xaffinity_propagation1= cluster.AffinityPropagation(damping=.65)
    xaffinity_propagation2= cluster.AffinityPropagation(damping=.8)
    xaffinity_propagation3= cluster.AffinityPropagation(damping=.95)

    algs = [k_means, k_means1, k_means2, k_means3,
            mini_kmeans, mini_kmeans2, mini_kmeans3, mini_kmeans4,
            ms, ms1, ms2, ms3,
            ward_k, ward_k1, ward_k2, ward_k3,
            spectral, spectral1,
            dbscan, dbscan2, dbscan3, dbscan4,
            affinity_propagation, affinity_propagation1,
            affinity_propagation2, affinity_propagation3,
            xaffinity_propagation, xaffinity_propagation1,
            xaffinity_propagation2, xaffinity_propagation3]

    scores = []

    for algorithm in algs:
        # Cluster features and find the best cluster afterwards.
        print '-----'
        print 'Clustering with', str(algorithm).split('(')[0]
        algorithm.fit(X)

        if hasattr(algorithm, 'labels_'):
            labels = algorithm.labels_.astype(np.int)
        else:
            labels = algorithm.predict(X)

        if hasattr(algorithm, 'cluster_centers_'):
            cluster_centers = algorithm.cluster_centers_
        else:
            cluster_centers = compute_centers(X, labels)

        scores.append(metrics.silhouette_score(X, labels))
        print 'silhouette SCORE', scores[-1]

        # Find the best cluster.
        maxi, max_mean = -1, None
        for i, feature_center in enumerate(cluster_centers):
            mean = np.mean(feature_center)
            if not max_mean or max_mean < mean:
                max_mean = mean
                maxi = i

        # Select all members from the cluster and print them.
        best_members = []
        for i, label in enumerate(labels):
            if label == maxi:
                best_members.append((names[i], all_features[i]))
        print get_top_members(best_members, 10)

    for i, alg in enumerate(algs):
        print str(alg).split('(')[0], scores[i]

    # Remove every reduced feature as they need to be recomputed
    # when one wants a plot of points.
    db[rfeatures_col(col)].remove()


def fetch_tweets(q, pages, col, lang='en', rpp=100):
    print 'Fetch tweets', q, pages, col
    # Make sure db is clean.
    db[col].remove({})
    page_count = 0

    # Send max_id, since_id as params
    #since_id = 475064331709972480 # halep sharapova
    #since_id = 478358845753131009 # gas russia ukraine
    since_id = None
    max_id = None
    while page_count < pages:
        tweets = api.search(q=q, lang=lang, count=rpp, max_id=max_id,
                            since_id=since_id)['statuses']
        db[col].insert(tweets)
        page_count += 1
        # Update the max_id based on those fetched, as twitter returns
        # tweets in id descending order.
        max_id = tweets[-1]['id'] - 1
        if page_count % 10 == 0:
            print 'Fetched pages', page_count
        # Avoid rate limit.
        time.sleep(5)
    print 'Done.'


def get_usernames(col):
    '''Returns a list of users (strings) from collection that:
       - wrote at least a number X of tweets about the topic (we assume that
         the collection holds data about only one given topic)
       - the X is just above the mean of posts of all users about the topic
    '''
    # http://docs.mongodb.org/manual/tutorial/aggregation-zip-code-data-set/
    # Compute the average number of posts for all users.
    avg = db[col].aggregate([
            {'$group': {'_id': '$user.screen_name', 'total': {'$sum': 1}}},
            {'$group': {'_id': None, 'avgNr': {'$avg': '$total'}}}
    ])['result'][0]['avgNr']
    user_names = db[col].aggregate([
                    {'$group': {'_id': '$user.screen_name',
                                'total': {'$sum': 1}}},
                    {'$match': {'total' : {'$gte': math.ceil(avg)}}}
                 ])
    user_names = map(lambda u: u['_id'], user_names['result'])
    return user_names


def exit():
    print 'Call like: ' + sys.argv[0] +\
          ' [fetch search pages][stats][compute search][plot collection]'
    sys.exit(1)


def main():
    if len(sys.argv) == 1:
        exit()
    # Fetch and store from twitter to db.
    if sys.argv[1] == 'fetch':
        assert len(sys.argv) == 4
        col = search = sys.argv[2]
        pages = int(sys.argv[3])
        # Save tweets for a given query in the collection with same name
        # for simplicity and consistency.
        fetch_tweets(search, pages, col)
    # Compute authorities by inspecting db.
    elif sys.argv[1] == 'compute':
        assert len(sys.argv) == 3
        col = search = sys.argv[2]
        find_authorities(search, col)
    elif sys.argv[1] == 'plot':
        assert len(sys.argv) == 3
        col = sys.argv[2]
        plot_features(col)
    # See rate limit info.
    elif sys.argv[1] == 'stats':
        pp = pprint.PrettyPrinter(indent=4)
        pp.pprint(api.rate_limit_status())
    else:
        exit()

if __name__ == '__main__':
    main()

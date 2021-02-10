#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jan 12 17:07:02 2021

@author: Lin-Jyun-Li
@The DDPG code was adapt from: https://github.com/MorvanZhou/Reinforcement-learning-with-tensorflow
"""
# -*- coding: utf-8 -*-


import os.path
import gurobipy as gp
from gurobipy import GRB
import scipy
import numpy
import gym
import mujoco_py
import numpy as np
import tensorflow as tf
import matplotlib.pyplot as plt
import math
import time
import random
tf.compat.v1.disable_eager_execution()
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '1,2'
os.environ['CUDA_VISIBLE_DEVICES'] = '1' 
os.environ['TF_DETERMINISTIC_OPS'] = '1'

env_name='HalfCheetah-v2'
env=gym.make(env_name)
s_dim = env.observation_space.shape[0] 
a_dim = env.action_space.shape[0]               
a_bound=env.action_space.high
ewma_r=0
arg_seed=0
#########################seed##############################
tf.compat.v1.reset_default_graph()
random.seed(arg_seed)
np.random.seed(arg_seed)
env.seed(arg_seed)
env.action_space.np_random.seed(arg_seed)
#####################  hyper parameters  ####################
exploration =0.1
LR_C=0.001
LR_A=0.0001
GAMMA=0.99
TAU=0.001
eval_freq=5000

MEMORY_CAPACITY=1000000
BATCH_SIZE=16
store_testing_before_action =[]
store_testing_after_action =[]
####################testing part#################################
def evaluation(env_name,seed,ddpg,eval_episode=10):
    avgreward=0
    avg=[]
    eval_env=gym.make(env_name)
    eval_env.seed(seed+100)
    for eptest in range(eval_episode):
        running_reward =0
        done=False
        s=eval_env.reset()
        while not done:     
            action= ddpg.choose_action(s)
            store_testing_before_action.append(action)
            action=Projection(action)
            store_testing_after_action.append(action)
            s_,r,done,info=eval_env.step(action)
            s=s_
            running_reward=running_reward+r
        print('Episode {}\tReward: {} \t AvgReward'.format(eptest, running_reward))
        avgreward=avgreward+running_reward
        avg.append(running_reward)
    avgreward=avgreward/eval_episode
    print("------------------------------------------------")
    print("Evaluation average reward :",avgreward)
    print("------------------------------------------------")

    return avgreward
###############################  DDPG  ####################################
fw=np.zeros((BATCH_SIZE,a_dim))

class DDPG(object):
    def __init__(self, a_dim, s_dim, a_bound,):
        self.memory = np.zeros((MEMORY_CAPACITY, s_dim * 2 + a_dim + 1+1), dtype=np.float32)
        self.pointer = 0
        configuration = tf.compat.v1.ConfigProto()
        configuration.gpu_options.allow_growth = True
        self.sess = tf.compat.v1.Session(config=configuration)
        #self.sess = tf.compat.v1.Session()
        tf.random.set_seed(arg_seed)
        
        self.a_dim, self.s_dim, self.a_bound = a_dim, s_dim, a_bound,
        self.S = tf.compat.v1.placeholder(tf.float32, [None, s_dim], 's')
        self.S_ = tf.compat.v1.placeholder(tf.float32, [None, s_dim], 's_')
        self.R = tf.compat.v1.placeholder(tf.float32, [None, 1], 'r')
        self.Done=tf.compat.v1.placeholder(tf.float32, [None, 1], 'done')
        
        self.tf_table=tf.compat.v1.placeholder(tf.float32, [None, a_dim], 'table')
        
        with tf.compat.v1.variable_scope('Actor'):
            self.a = self._build_a(self.S, scope='eval', trainable=True)
            a_ = self._build_a(self.S_, scope='target', trainable=False)
        with tf.compat.v1.variable_scope('Critic'):
           
            self.q = self._build_c(self.S, self.a, scope='eval', trainable=True)
            q_ = self._build_c(self.S_, a_, scope='target', trainable=False)

        # networks parameters
        self.ae_params = tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.GLOBAL_VARIABLES, scope='Actor/eval')
        self.at_params = tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.GLOBAL_VARIABLES, scope='Actor/target')
        self.ce_params = tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.GLOBAL_VARIABLES, scope='Critic/eval')
        self.ct_params = tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.GLOBAL_VARIABLES, scope='Critic/target')

        # target net replacement
        self.soft_replace = [tf.compat.v1.assign(t, (1 - TAU) * t + TAU * e)
                             for t, e in zip(self.at_params + self.ct_params, self.ae_params + self.ce_params)]

        q_target = self.R + (1-self.Done)*GAMMA * q_
        td_error = tf.compat.v1.losses.mean_squared_error(labels=q_target, predictions=self.q)
        self.ctrain = tf.compat.v1.train.AdamOptimizer(LR_C).minimize(td_error, var_list=self.ce_params)
        
        action_td_error = tf.compat.v1.losses.mean_squared_error(labels=self.tf_table, predictions=self.a)
        self.update = tf.compat.v1.train.AdamOptimizer(LR_A).minimize(action_td_error, var_list=self.ae_params)
        
        self.action_grad=tf.gradients(self.q,self.a)
        
        self.sess.run(tf.compat.v1.global_variables_initializer())

    def choose_action(self, s):
       
        return self.sess.run(self.a, {self.S: s[np.newaxis, :]})[0]

    def learn(self):
        # soft target replacement
        self.sess.run(self.soft_replace)
        buffer_size= min(ddpg.pointer+1,MEMORY_CAPACITY)
        indices = np.random.choice(buffer_size, size=BATCH_SIZE)
        bt = self.memory[indices, :]
        bs = bt[:, :self.s_dim]
        ba = bt[:, self.s_dim: self.s_dim + self.a_dim]
        br=  bt[:,self.s_dim+self.a_dim:self.s_dim+self.a_dim+1]
        bs_ = bt[:,self.s_dim+self.a_dim+1:self.s_dim+self.a_dim+1+self.s_dim]
        bd = bt[:,-1:]
        self.sess.run(self.ctrain, {self.S: bs, self.a: ba, self.R: br, self.S_: bs_,self.Done:bd})

    def store_transition(self, s, a, r, s_,done):
        transition = np.hstack((s, a, [r], s_,done))
        index = self.pointer % MEMORY_CAPACITY  # replace the old memory with new memory
        self.memory[index, :] = transition
        self.pointer += 1

    def _build_a(self, s, scope, trainable):
        with tf.compat.v1.variable_scope(scope):
            net = tf.compat.v1.layers.dense(s, 400, activation=tf.nn.relu, name='l1', trainable=trainable)
            net2 = tf.compat.v1.layers.dense(net,300, activation=tf.nn.relu, name='l2', trainable=trainable)
            a = tf.compat.v1.layers.dense(net2, self.a_dim, activation=tf.nn.tanh, name='a', trainable=trainable)
            return tf.multiply(a, self.a_bound, name='scaled_a')

    def _build_c(self, s, a, scope, trainable):
        with tf.compat.v1.variable_scope(scope):
            net = tf.compat.v1.layers.dense(s, 400, activation=tf.nn.relu, name='cl1', trainable=trainable)
            #net2 = tf.compat.v1.layers.dense(tf.concat[net,a], 300, activation=tf.nn.relu, name='cl1', trainable=trainable)
            w2_net = tf.compat.v1.get_variable('w2_net', [400, 300], trainable=trainable)
            w2_a = tf.compat.v1.get_variable('w2_a', [self.a_dim, 300], trainable=trainable)
            b2= tf.compat.v1.get_variable('b1', [1, 300], trainable=trainable)
            net2= tf.nn.relu(tf.matmul(a,w2_a)+tf.matmul(net,w2_net)+b2)
            return tf.compat.v1.layers.dense(net2, 1, trainable=trainable)  # Q(s,a)
    def get_gradient(self,s,a):
        return self.sess.run(self.action_grad,{self.S: s, self.a: a})
    def fw_update(self):
        lr=0.01
        indices = np.random.choice(MEMORY_CAPACITY, size=BATCH_SIZE)
        bt = self.memory[indices, :]
        bs = bt[:, :self.s_dim]
        ba=self.sess.run(self.a,{self.S:bs})
        #######Let ba in constaint######
        for i in range(BATCH_SIZE) :
            if (np.sqrt(ba[i][0]**2+ba[i][1]**2+ba[i][2]**2)<=1e-6+2.25)  and (np.sqrt(ba[i][3]**2+ba[i][4]**2+ba[i][5]**2)<=1e-6+2.25):
                pass
            else :
                ba[i]=Projection(ba[i])
                
        #######Let ba in constaint######
        grad=self.get_gradient(bs,ba)
        grad=np.squeeze(grad)
        action_table=np.zeros((BATCH_SIZE,self.a_dim))   #(16,16,2
        for i in range(BATCH_SIZE):
            with gp.Env(empty=True) as env:
                env.setParam('OutputFlag', 0)
                env.start()
                with gp.Model(env=env) as fw_m:
                    a1 = fw_m.addVar(lb=-1,ub=1, name="a1",vtype=GRB.CONTINUOUS)
                    a2 = fw_m.addVar(lb=-1,ub=1, name="a2",vtype=GRB.CONTINUOUS)
                    a3 = fw_m.addVar(lb=-1,ub=1, name="a3",vtype=GRB.CONTINUOUS)
                    a4 = fw_m.addVar(lb=-1,ub=1, name="a4",vtype=GRB.CONTINUOUS)
                    a5 = fw_m.addVar(lb=-1,ub=1, name="a5",vtype=GRB.CONTINUOUS)
                    a6 = fw_m.addVar(lb=-1,ub=1, name="a6",vtype=GRB.CONTINUOUS)
                    
                    obj= a1*grad[i][0]+a2*grad[i][1]+a3*grad[i][2]+a4*grad[i][3]+a5*grad[i][4]+a6*grad[i][5]
                    fw_m.setObjective(obj,GRB.MAXIMIZE)
                    fw_m.addConstr((a1**2+a2**2+a3**2)<=1)
                    fw_m.addConstr((a4**2+a5**2+a6**2)<=1)
                    fw_m.optimize()
                    action_table[i][0]=a1.X
                    action_table[i][1]=a2.X
                    action_table[i][2]=a3.X
                    action_table[i][3]=a4.X
                    action_table[i][4]=a5.X
                    action_table[i][5]=a6.X
                    
                    
                    fw_m.reset()
                fw[i]=action_table[i]
                action_table[i]=action_table[i]*lr+ba[i] *(1-lr)
        self.sess.run(self.update,{self.S:bs,self.tf_table:action_table})
ddpg = DDPG(a_dim,s_dim,a_bound)    
#############################  Projection  ####################################

def Projection(action):
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag', 0)
        env.start()
        with gp.Model(env=env) as half_m:
            joint1_a1=action[0]
            joint1_a2=action[1]
            joint2_a1=action[2]
            joint2_a2=action[3]
            joint3_a1=action[4]
            joint3_a2=action[5]
           
           
            a1 = half_m.addVar(lb=-1,ub=1, name="a1",vtype=GRB.CONTINUOUS)
            a2 = half_m.addVar(lb=-1,ub=1, name="a2",vtype=GRB.CONTINUOUS)
            a3 = half_m.addVar(lb=-1,ub=1, name="a3",vtype=GRB.CONTINUOUS)
            a4 = half_m.addVar(lb=-1,ub=1, name="a4",vtype=GRB.CONTINUOUS)
            a5 = half_m.addVar(lb=-1,ub=1, name="a5",vtype=GRB.CONTINUOUS)
            a6 = half_m.addVar(lb=-1,ub=1, name="a6",vtype=GRB.CONTINUOUS)
            
            obj= (a1-joint1_a1)**2+ (a2-joint1_a2)**2+(a3-joint2_a1)**2+(a4-joint2_a2)**2+(a5-joint3_a1)**2+(a6-joint3_a2)**2
            half_m.setObjective(obj,GRB.MINIMIZE)
            
            half_m.addConstr((a1**2+a2**2+a3**2)<=1)
            half_m.addConstr((a4**2+a5**2+a6**2)<=1)



            half_m.optimize()
        
            return a1.X,a2.X,a3.X,a4.X,a5.X,a6.X
            
##################################################################################

Net_action=np.zeros((1000000,a_dim+2))   
ewma = []
eva_reward=[]
store_before_action_and_gaussain=[]
store_before_action=[]
store_after_action =[]
max_action = float(env.action_space.high[0])

reward=[]
var=3
step=0
for ep in range(1000000):
    #env.render()
    R=0
    step=0
    done=False
    s=env.reset()
    while not done:
        step=step+1
        #use gaussian exploration by TD3 (0,0.1) to each action
        if ddpg.pointer<10000:
            action=env.action_space.sample()
            store_before_action.append(action)
        else :
            action=ddpg.choose_action(s)
            store_before_action_and_gaussain.append(action)
            action=action+np.random.normal(0,0.1,a_dim).clip(-max_action,max_action)
            store_before_action.append(action)
        action=Projection(action)
        store_after_action.append(action)

        assert np.sqrt(action[0]**2+action[1]**2+action[2]**2)<=1e-6+1
        assert np.sqrt(action[3]**2+action[4]**2+action[5]**2)<=1e-6+1
        
        s_,r,done,info=env.step(action)
        done_bool = False if step==1000 else done 
        ddpg.store_transition(s,action,r,s_,done_bool)
        if ddpg.pointer>=10000:
            ddpg.learn()
            ddpg.fw_update()
            
        s= s_
        R += r
    reward.append(R)
    ewma_r = 0.05 * R + (1 - 0.05) * ewma_r
    if(ddpg.pointer>=10000):
        print("start_training,ddpgpointer:{}".format(ddpg.pointer))
    print({
        'episode': ep,
        'reward' :R,
        'ewma_reward' :ewma_r
    })
    ewma.append(ewma_r)
    if(ddpg.pointer>=1000000):
        print("done training")
        break
a=[]
for i in range(ep+1):
    a.append(i)
plt.plot(a,ewma)
plt.title("ewma reward, final ewma={}".format(ewma[ep]))  

np.save("Halfcheetah_{}_DDPGFW_Reward_Cons1".format(arg_seed),reward)
np.save("Halfcheetah_{}_DDPGFW_before_Action_Cons1".format(arg_seed),store_before_action)
np.save("Halfcheetah_{}_DDPGFW_after_Action_Cons1".format(arg_seed),store_after_action)
np.save("Halfcheetah_{}_DDPGFW_eval_reward_Cons1".format(arg_seed),eva_reward)
np.save("Halfcheetah_{}_DDPGFW_before_Action_Gaussian_Cons1".format(arg_seed),store_before_action_and_gaussain)
np.save("Halfcheetah_{}_DDPGFW_eval_before_Action_Cons1".format(arg_seed),store_testing_before_action)
np.save("Halfcheetah_{}_DDPGFW_eval_After_Action_Cons1".format(arg_seed),store_testing_after_action)



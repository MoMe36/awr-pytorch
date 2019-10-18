import random
from collections import deque

import gym
from torch.multiprocessing import Process

from model import *


class CartPoleEnvironment(Process):
    def __init__(self, env_id, is_render):
        super(CartPoleEnvironment, self).__init__()
        self.daemon = True
        self.env = gym.make(env_id)

        self.is_render = is_render
        self.steps = 0
        self.episode = 0
        self.rall = 0
        self.recent_rlist = deque(maxlen=100)
        self.recent_rlist.append(0)

        self.reset()

    def step(self, action):
        if self.is_render:
            self.env.render()

        obs, reward, done, info = self.env.step(action)
        self.rall += reward
        self.steps += 1

        if done:
            if self.steps < self.env.spec.max_episode_steps:
                reward = -1

            self.recent_rlist.append(self.rall)
            print("[Episode {}] Reward: {}  Recent Reward: {}".format(
                self.episode, self.rall, np.mean(self.recent_rlist)))
            obs = self.reset()

        return obs, reward, done, info

    def reset(self):
        self.steps = 0
        self.episode += 1
        self.rall = 0

        return np.array(self.env.reset())


class ActorAgent(object):
    def __init__(
            self,
            input_size,
            output_size,
            gamma,
            lam=0.95,
            use_gae=True,
            use_cuda=False,
            use_noisy_net=False):
        self.model = BaseActorCriticNetwork(
            input_size, output_size, use_noisy_net)
        self.output_size = output_size
        self.input_size = input_size
        self.gamma = gamma
        self.lam = lam
        self.use_gae = use_gae
        self.actor_optimizer = optim.SGD(self.model.actor.parameters(),
                                         0.00005, momentum=0.9)
        self.critic_optimizer = optim.SGD(self.model.critic.parameters(),
                                          0.001, momentum=0.9)
        self.device = torch.device('cuda' if use_cuda else 'cpu')
        self.model = self.model.to(self.device)

    def get_action(self, state):
        state = torch.Tensor(state).to(self.device)
        state = state.float()
        policy, value = self.model(state)
        policy = F.softmax(policy, dim=-1).data.cpu().numpy()

        action = np.random.choice(np.arange(self.output_size), p=policy)

        return action

    def train_model(self, s_batch, action_batch, reward_batch, n_s_batch, done_batch):
        s_batch = np.array(s_batch)
        action_batch = np.array(action_batch)
        reward_batch = np.array(reward_batch)
        done_batch = np.array(done_batch)

        data_len = len(s_batch)
        mse = nn.MSELoss()

        # update critic
        self.critic_optimizer.zero_grad()
        cur_value = self.model.critic(torch.FloatTensor(s_batch))
        discounted_reward, _ = discount_return(reward_batch, done_batch, cur_value.cpu().detach().numpy())
        # discounted_reward = (discounted_reward - discounted_reward.mean())/(discounted_reward.std() + 1e-8)
        for _ in range(critic_update_iter):
            sample_idx = random.sample(range(data_len), 256)
            sample_value = self.model.critic(torch.FloatTensor(s_batch[sample_idx]))
            critic_loss = mse(sample_value.squeeze(), torch.FloatTensor(discounted_reward[sample_idx]))
            critic_loss.backward()
            self.critic_optimizer.step()
            self.critic_optimizer.zero_grad()

        # update actor
        cur_value = self.model.critic(torch.FloatTensor(s_batch))
        discounted_reward, adv = discount_return(reward_batch, done_batch, cur_value.cpu().detach().numpy())
        # adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        self.actor_optimizer.zero_grad()
        for _ in range(actor_update_iter):
            sample_idx = random.sample(range(data_len), 256)
            cur_policy = self.model.actor(torch.FloatTensor(s_batch[sample_idx]))
            m = Categorical(F.softmax(cur_policy, dim=-1))

            weight = np.minimum(np.exp(adv[sample_idx] / beta), max_weight)

            actor_loss = -m.log_prob(torch.LongTensor(action_batch[sample_idx])) * torch.FloatTensor(weight)
            actor_loss = actor_loss.mean()

            actor_loss.backward()
            self.actor_optimizer.step()
            self.actor_optimizer.zero_grad()


def discount_return(reward, done, value):
    value = value.squeeze()
    num_step = len(value)
    discounted_return = np.zeros([num_step])

    gae = 0
    for t in range(num_step - 1, -1, -1):
        if dones[t]:
            delta = reward[t] - value[t]
        else:
            delta = reward[t] + gamma * value[t + 1] - value[t]
        gae = delta + gamma * lam * (1 - done[t]) * gae

        discounted_return[t] = gae + value[t]

    # For Actor
    adv = discounted_return - value
    return discounted_return, adv


if __name__ == '__main__':
    env_id = 'CartPole-v1'
    env = gym.make(env_id)
    input_size = env.observation_space.shape[0]  # 4
    output_size = env.action_space.n  # 2
    env.close()

    use_cuda = False
    use_noisy_net = False
    batch_size = 256
    num_sample = 2048
    critic_update_iter = 500
    actor_update_iter = 1000
    iteration = 100000
    max_replay = 50000

    gamma = 0.99
    lam = 0.95
    beta = 1.0
    max_weight = 20.0
    use_gae = True

    agent = ActorAgent(
        input_size,
        output_size,
        gamma,
        use_gae=use_gae,
        use_cuda=use_cuda,
        use_noisy_net=use_noisy_net)
    is_render = False

    env = CartPoleEnvironment(env_id, is_render)

    states, actions, rewards, next_states, dones = deque(maxlen=max_replay), deque(maxlen=max_replay), deque(
        maxlen=max_replay), deque(maxlen=max_replay), deque(maxlen=max_replay)

    last_done_index = -1

    for i in range(iteration):
        done = False
        score = 0

        step = 0
        episode = 0
        state = env.reset()

        while True:
            step += 1
            action = agent.get_action(state)

            next_state, reward, done, info = env.step(action)
            states.append(np.array(state))
            actions.append(action)
            rewards.append(reward)
            next_states.append(np.array(next_state))
            dones.append(done)

            state = next_state[:]

            if done:
                episode += 1

                state = env.reset()
                if step > num_sample:
                    step = 0
                    # train
                    agent.train_model(states, actions, rewards, next_states, dones)

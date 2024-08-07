# Copyright (c) 2016, the GPyOpt Authors
# Licensed under the BSD 3-clause license (see LICENSE.txt)

# Authors: 	Armi Tiihonen, Felipe Oviedo, Shreyaa Raghavan, Zhe Liu
# MIT Photovoltaics Laboratory

import pandas as pd  # Added
import numpy as np  # Added
import GPy  # Added
import matplotlib # Added
import matplotlib.pyplot as plt # Added
from plotting_v2 import triangleplot # Added

from .base import AcquisitionBase
from ..util.general import get_quantiles

#import logging


class AcquisitionEI_DFT(AcquisitionBase):
    """
    Expected improvement acquisition function

    :param model: GPyOpt class of model
    :param space: GPyOpt class of domain
    :param optimizer: optimizer of the acquisition. Should be a GPyOpt optimizer
    :param cost_withGradients: function
    :param jitter: positive value to make the acquisition more explorative.

    .. Note:: allows to compute the Improvement per unit of cost

    """

    analytical_gradient_prediction = True

    def __init__(self, model, space, optimizer=None, cost_withGradients=None, jitter=0.01, ei_dft_params=None):
        
        self.optimizer = optimizer
        super(AcquisitionEI_DFT, self).__init__(model, space, optimizer, cost_withGradients=cost_withGradients)
        self.jitter = jitter
        #print(jitter)
        if ei_dft_params is None:
            
            # Default values.
            
            ei_dft_params = {'df_data': None,
                         'df_target_var': None,
                         'df_input_var': None,
                         'gp_lengthscale': 0.03,
                         'gp_variance': 2,
                         'p_beta': 0.025,
                         'p_midpoint': 0,
                         'df_model': None
                         }
        
        if 'df_target_var' in ei_dft_params:
            self.data_fusion_target_variable = ei_dft_params['df_target_var']
        else:
            self.data_fusion_target_variable = None
        
        if 'df_input_var' in ei_dft_params:
            self.data_fusion_input_variables = ei_dft_params['df_input_var']
        else:
            self.data_fusion_input_variables = None
        
        if 'df_model' in ei_dft_params:
            
            # GPY GPRegression model.
            self.constraint_model = ei_dft_params['df_model']
            # Data is not used for anything if the model already exists.
            self.data_fusion_data = None
            
        else:
            
            if 'df_data' in ei_dft_params:
                self.data_fusion_data = ei_dft_params['df_data']
            else:
                self.data_fusion_data = None
            
            # Initialize to the given values.
            if 'gp_lengthscale' in ei_dft_params:
                self.lengthscale = ei_dft_params['gp_lengthscale']
            else:
                self.lengthscale = 0.03
                
            if 'gp_variance' in ei_dft_params:
                self.variance = ei_dft_params['gp_variance']
            else:
                self.variance = 2

            self.constraint_model = GP_model(self.data_fusion_data,
                                             data_fusion_target_variable = self.data_fusion_target_variable,
                                             lengthscale = self.lengthscale,
                                             variance = self.variance, 
                                             data_fusion_input_variables = self.data_fusion_input_variables)  # Added
        
        # Let's update with the fitted model hyperparameter values.
        self.lengthscale = self.constraint_model.kern.lengthscale
        self.variance = self.constraint_model.kern.variance
        
        if 'p_beta' in ei_dft_params:
            self.beta = ei_dft_params['p_beta']
        else:
            self.beta = 0.025

        if 'p_midpoint' in ei_dft_params:
            self.midpoint = ei_dft_params['p_midpoint']
        else:
            self.beta = 0

            
            
        if len(self.data_fusion_input_variables) == 3:
            
            # Plot the data.
            if self.data_fusion_target_variable == 'dGmix (ev/f.u.)':
                plot_P(self.constraint_model, beta = self.beta, data_type = 'dft', midpoint = self.midpoint)
            if self.data_fusion_target_variable == 'Yellowness':
                plot_P(self.constraint_model, beta = self.beta, data_type = 'yellowness', midpoint = self.midpoint)
        
        else:
            
            message = 'I do not know how to plot this data fusion variable.'
            #logging.error(message)

    @staticmethod
    def fromConfig(model, space, optimizer, cost_withGradients, jitter, ei_dft_params, config):
        return AcquisitionEI_DFT(model, space, optimizer, cost_withGradients, jitter)

    def _compute_acq(self, x):
        """
        Computes the Expected Improvement per unit of cost
        """
        m, s = self.model.predict(x)
        fmin = self.model.get_fmin()
        phi, Phi, u = get_quantiles(self.jitter, fmin, m, s)
        f_acqu = s * (u * Phi + phi)
        
        _, prob = calc_P(x, self.constraint_model, self.beta, self.midpoint) # Added
        f_acqu = f_acqu * prob # Added
        
        message = 'Exploitation ' + str(s*u*Phi*prob) + ', exploration ' + str(s*phi*prob) # Added
        #logging.debug(message)
        
        return f_acqu

    def _compute_acq_withGradients(self, x):
        """
        Computes the Expected Improvement and its derivative (has a very easy derivative!)
        """
        fmin = self.model.get_fmin()
        m, s, dmdx, dsdx = self.model.predict_withGradients(x)
        phi, Phi, u = get_quantiles(self.jitter, fmin, m, s)
        f_acqu = s * (u * Phi + phi)
        df_acqu = dsdx * phi - Phi * dmdx
        
        if np.any(np.isnan(x)):
            message = 'x contains nan:\n ' + str(x)
            #logging.error(message)
        
        _, prob = calc_P(x, self.constraint_model, self.beta, self.midpoint) # Added
        
        #print('x='+str(x)+', acqu='+str(f_acqu)+', grad_acqu='+str(df_acqu),
        #      ', P=' + str(prob))
        
        f_acqu = f_acqu * prob # Added
        
        d_prob = calc_gradient_of_P(x, self.constraint_model, self.beta,
                                    self.midpoint, self.lengthscale)
        
        df_acqu = df_acqu * prob + f_acqu * d_prob
        
        #print('acqu_P='+str(f_acqu)+', grad_acqu_P='+str(df_acqu))
        
        return f_acqu, df_acqu

def calc_gradient_of_P(x, constraint_model, beta, midpoint, lengthscale):
    
    # Step for numerical gradient.
    delta_x = lengthscale/1000
    
    g = np.empty(x.shape)
    
    for i in range(x.shape[1]):
        
        x_l = x.copy()
        x_u = x.copy()
        
        x_l[:,i] = x_l[:,i] - delta_x
        x_u[:,i] = x_u[:,i] + delta_x
        
        _, p_l = calc_P(x_l, constraint_model, beta, midpoint)
        #_, p_c = calc_P(x, constraint_model, beta, midpoint)
        _, p_u = calc_P(x_u, constraint_model, beta, midpoint)
        
        g[:,i] =  np.ravel((p_u - p_l)/(2*delta_x))
        
        return g
        

# Added the rest of the file on 2021/11/02.
def GP_model(data_fusion_data, data_fusion_target_variable = 'dGmix (ev/f.u.)', 
             lengthscale = 0.03, variance = 2, noise_variance = None,
             data_fusion_input_variables = ['CsPbI', 'MAPbI', 'FAPbI']):
    
    if data_fusion_data is None:
        
        model = None
        
    else:
    
        if data_fusion_data.empty:
            
            model = None
            
        else:
            
            X = data_fusion_data[data_fusion_input_variables] # This is 3D input
            Y = data_fusion_data[[data_fusion_target_variable]] # Negative value: stable phase. Uncertainty = 0.025 
            X = X.values # Optimization did not succeed without type conversion.
            Y = Y.values
            
            # Init value for noise_var, GPy will optimize it further.
            noise_var = noise_variance
            noise_var_limit = 1e-12
            
            if (noise_var is None) or (noise_var <= 0):
                
                noise_var = 0.01*Y.var()
                
                # Noise_variance should not be zero.
                if noise_var == 0:
                    
                    noise_var = noise_var_limit
                
            #message = ('Human Gaussian noise variance in data and model input: ' +
            #           str(Y.var()) + ', ' + str(noise_var) + '\n' +
            #           'Human model data:' + str(Y))
            #print(message)
            #logging.log(21, message)
            
            # Set hyperparameter initial guesses.
            
            kernel_var = variance
            
            if (kernel_var is None) or (kernel_var <= 0):
                
                kernel_var = Y.var()
                
                if kernel_var == 0: # Only constant value(s)
                    
                    kernel_var = 1
                
            kernel_ls = lengthscale
            
            if (kernel_ls is None) or (kernel_ls <= 0):
                
                kernel_ls = X.max()-X.min()
                
                if kernel_ls == 0: # Only constant value(s)
                    
                    kernel_ls = 1
                    
            # Define the kernel and model.
            
            kernel = GPy.kern.Matern52(input_dim=X.shape[1], 
                                  lengthscale=kernel_ls, variance=kernel_var)
            
            model = GPy.models.GPRegression(X,Y,kernel, noise_var = noise_var)
            
            # --- We make sure we do not get ridiculously small residual noise variance
            # The upper bound is set to the noise level that corresponds to the
            # maximum Y value in the dataset.
            model.Gaussian_noise.constrain_bounded(noise_var_limit, noise_var + (Y.max())**2, warning=False)
            
            # With small number of datapoints and no bounds on variance, the
            # model sometimes converged into ridiculous kernel variance values.
            model.Mat52.variance.constrain_bounded(variance*1e-12, variance + (Y.max())**2, 
                                                 warning=False)
            
            # optimize
            model.optimize_restarts(max_iters = 1000, num_restarts=5)
            
            #message = ('Human Gaussian noise variance in model output: ' + 
            #           str(model.Gaussian_noise.variance[0]))
            #logging.log(21, message)
            
    return model
    
def calc_P(points, GP_model, beta = 0.025, midpoint = 0):
    
    #print(points)
    if GP_model is not None:
        mean = GP_model.predict_noiseless(points)
        mean = mean[0] # TO DO: issue here with dimensions?
        #print(mean)
        #conf_interval = GP_model.predict_quantiles(np.array(points)) # 95% confidence interval by default. TO DO: Do we want to use this for something?
        conf_interval = None
        propability = inv_sigmoid(mean, midpoint, beta)
    
    else:
        
        mean = np.zeros(shape = (points.shape[0], 1)) + 0.5
        #conf_interval = [np.zeros(shape = (points.shape[0], 1)),
        #                 np.ones(shape = (points.shape[0], 1))]
        propability= np.ones(shape = (points.shape[0], 1))
        
    return mean, propability#, conf_interval

def inv_sigmoid(mean, midpoint, beta):
    
    # Inverted because the negative Gibbs energies are the ones that are stable.
    f = 1/(1+np.exp((mean-midpoint)/beta))
    
    return f
    

def create_ternary_grid(range_min=0, range_max=1, interval=0.005):

    ### This grid is used for plotting the posterior mean and std_dv + acq function.
    a = np.arange(range_min, range_max, interval)
    xt, yt, zt = np.meshgrid(a,a,a, sparse=False)
    points = np.transpose([xt.ravel(), yt.ravel(), zt.ravel()])
    # The x, y, z coordinates need to sum up to 1 in a ternary grid.
    points = points[abs(np.sum(points, axis=1)-1) < interval]
    
    return points

def plot_surf_mean(points, posterior_mean, lims, axis_scale = 1,
                   cbar_label = r'$I_{c}(\theta)$ (px$\cdot$h)',
                   saveas = 'Ic-no-grid'):
    
    norm = matplotlib.colors.Normalize(vmin=lims[0][0], vmax=lims[0][1])    
    y_data = posterior_mean/axis_scale
    plot_surf(points, y_data, norm, cbar_label = cbar_label, saveas = saveas)

def plot_surf(points, y_data, norm, cmap = 'RdBu_r', cbar_label = '',
              saveas = 'Triangle_surf'):

    #print(y_data.shape, points.shape)
    #print(norm)
    #print(cmap)
    triangleplot(points, y_data, norm, cmap = cmap,
                 cbar_label = cbar_label, saveas = saveas)


def plot_P(GP_model, beta = 0.025, data_type = 'dft', midpoint = 0):
        
    points = create_ternary_grid()
    lims = [[0,1], [0,1]] # For mean and std. Std lims are not actually used for P.
    
    if data_type == 'stability':
        cbar_label_mean = r'$P_{Ic}$'
        saveas_mean = 'P-Ic-no-grid' + np.datetime_as_string(np.datetime64('now'))
    elif data_type == 'dft':
        cbar_label_mean = r'$P_{phasestable}$'
        saveas_mean = 'P-dGmix-no-grid' + np.datetime_as_string(np.datetime64('now'))
    elif data_type == 'uniformity':
        cbar_label_mean = r'P_{uniform}'
        saveas_mean = 'P-Uniformity-no-grid' + np.datetime_as_string(np.datetime64('now'))
    elif data_type == 'yellowness':
        cbar_label_mean = r'$P_{dark}$'
        saveas_mean = 'P-Yellowness-no-grid-' + np.datetime_as_string(np.datetime64('now'))
    else:
        cbar_label_mean = r'P'
        saveas_mean = 'P-no-grid'

    mean, propability, conf_interval = calc_P(points, GP_model, beta = beta, midpoint = midpoint)
    
    minP = np.min(propability)
    maxP = np.max(propability)
        
    return minP, maxP

# For testing of GP_model() and mean_and_propability():
'''
model = GP_model()
model.plot(visible_dims=[0,2])
model.plot(visible_dims=[0,1])
model.plot(visible_dims=[1,2])
x1 = np.linspace(0,1,20)
x2 = np.ones(x1.shape) - x1
x3 = np.zeros(x1.shape)
x_CsMA = np.column_stack([x1,x2,x3]) #[[0.5,0,0.5], [0.5, 0.5, 0], [0, 0.5, 0.5], [0.25,0.5,0.25], [0.5,0.25,0.25], [0.25,0.25,0.5]])
mean_CsMA, P_CsMA, conf_interval = mean_and_propability(x_CsMA, model)
x_CsFA = np.column_stack([x2,x3,x1]) #[[0.5,0,0.5], [0.5, 0.5, 0], [0, 0.5, 0.5], [0.25,0.5,0.25], [0.5,0.25,0.25], [0.25,0.25,0.5]])
mean_CsFA, P_CsFA, conf_interval = mean_and_propability(x_CsFA, model)
x_MAFA = np.column_stack([x3,x1,x2]) #[[0.5,0,0.5], [0.5, 0.5, 0], [0, 0.5, 0.5], [0.25,0.5,0.25], [0.5,0.25,0.25], [0.25,0.25,0.5]])
mean_MAFA, P_MAFA, conf_interval = mean_and_propability(x_MAFA, model)

plt.show()
mpl.rcParams.update({'font.size': 22})
fig, ax = plt.subplots()
fig2, ax2 = plt.subplots()
ax.set(xlabel='% of compound', ylabel='dGmix (ev/f.u.)',
       title='Modelled Gibbs energy')
ax2.set(xlabel='% compound', ylabel='P(is stable)',
       title='Modelled probability distribution')
ax.grid()
ax2.grid()
ax.plot(x1, mean_CsMA, label='Mean, Cs in CsMA')
ax.plot(x1, mean_CsFA, label = 'Mean, FA in CsFA')
ax.plot(x1, mean_MAFA, label ='Mean, MA in MAFA')
ax.legend()

ax2.plot(x1, P_CsMA, '--', label='P, Cs in CsMA')
ax2.plot(x1, P_CsFA, '--', label='P, FA in CsFA')
ax2.plot(x1, P_MAFA, '--', label='P, MA in MAFA')
ax2.legend()

x = np.linspace(-2,2,200)
y1 = 1/(1+np.exp(x/0.2))
y2 = 1/(1+np.exp(x/0.025))

fig3, ax3 = plt.subplots()
ax3.set(xlabel='x i.e. Gibbs energy', ylabel='inverted sigmoid i.e. P')
ax3.grid()
ax3.plot(x, y1, label = 'scale 0.2')
ax3.plot(x, y2, label = 'scale 0.025')
ax3.legend()

fig4, ax4 = plt.subplots()
ax4.set(xlabel='x', ylabel='inverted sigmoid')
ax4.grid()
ax4.plot(x, y1, label = 'scale 0.2')
ax4.plot(x, y2, label = 'scale 0.025')
ax4.set_xlim(-0.2, 0.2)


plt.show()
'''

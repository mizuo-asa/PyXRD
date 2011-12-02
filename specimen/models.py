# coding=UTF-8
# ex:ts=4:sw=4:et=on

# Author: Mathijs Dumon
# This work is licensed under the Creative Commons Attribution-ShareAlike 3.0 Unported License. 
# To view a copy of this license, visit http://creativecommons.org/licenses/by-sa/3.0/ or send
# a letter to Creative Commons, 444 Castro Street, Suite 900, Mountain View, California, 94041, USA.

import os

import gtk
import gobject

from gtkmvc import Observable
from gtkmvc.model import ListStoreModel, Model, Signal, Observer

import matplotlib
import matplotlib.transforms as transforms
from matplotlib.text import Text

import numpy as np
from scipy import stats

from math import tan, asin, sin, cos, pi, sqrt, radians, degrees, exp

from generic.utils import interpolate, erf
from generic.io import Storable, PyXRDDecoder
from generic.models import XYData, ChildModel
from generic.treemodels import ObjectListStore, XYListStore, Point
from generic.peak_detection import multi_peakdetect, peakdetect, smooth


class Specimen(ChildModel, Observable, Storable):

    __columns__ = [
        ('data_name', str),
        ('data_sample', str),
        ('data_sample_length', str),
        ('display_calculated', bool),
        ('display_experimental', bool),
        ('display_phases', bool),
        ('data_phases', object),
        ('data_calculated_pattern', object),
        ('data_experimental_pattern', object),
        ('data_markers', object),
        ('inherit_calc_color', bool),
        ('calc_color', str),
        ('inherit_exp_color', bool),
        ('exp_color', str),
    ]
    __observables__ = [ key for key, val in __columns__]
    __storables__ = [ val for val in __observables__ if val is not 'data_phases']

    data_name = ""
    data_sample = ""  ##TODO self.parent.data_specimens.on_item_changed(self)
    
    _data_sample_length = 3.0
    @Model.getter("data_sample_length")
    def get_data_sample_length(self, prop_name):
        return self._data_sample_length
    @Model.setter("data_sample_length")
    def set_data_sample_length(self, prop_name, value):
        self._data_sample_length = value    
    #data_sample_length = 0
    
    display_calculated = True
    display_experimental = True
    display_phases = False
    
    data_calculated_pattern = None
    data_experimental_pattern = None
    
    __pctrl__ = None
    
    _inherit_calc_color = True
    @Model.getter("inherit_calc_color")
    def get_inherit_calc_color(self, prop_name):
        return self._inherit_calc_color
    @Model.setter("inherit_calc_color")
    def set_inherit_calc_color(self, prop_name, value):
        if value != self._inherit_calc_color:
            self._inherit_calc_color = value
            if self.data_calculated_pattern != None:
                self.data_calculated_pattern.color = self.calc_color
    
    _calc_color = "#666666"
    @Model.getter("calc_color")
    def get_calc_color(self, prop_name):
        if self.inherit_calc_color and self.parent!=None:
            return self.parent.display_calc_color
        else:
            return self._calc_color
    @Model.setter("calc_color")
    def set_calc_color(self, prop_name, value):
        if value != self._calc_color:
            self._calc_color = value
            self.data_calculated_pattern.color = self.calc_color
            
    _inherit_exp_color = True
    @Model.getter("inherit_exp_color")
    def get_inherit_exp_color(self, prop_name):
        return self._inherit_exp_color
    @Model.setter("inherit_exp_color")
    def set_inherit_exp_color(self, prop_name, value):
        if value != self._inherit_exp_color:
            self._inherit_exp_color = value
            if self.data_experimental_pattern != None:
                self.data_experimental_pattern.color = self.exp_color
            
    _exp_color = "#000000"
    @Model.getter("exp_color")
    def get_exp_color(self, prop_name):
        if self.inherit_exp_color and self.parent!=None:
            return self.parent.display_exp_color
        else:
            return self._exp_color
    @Model.setter("exp_color")
    def set_exp_color(self, prop_name, value):
        if value != self._exp_color:
            self._exp_color = value
            self.data_experimental_pattern.color = value
    
    def set_display_offset(self, new_offset):
        self.data_experimental_pattern.display_offset = new_offset
        self.data_calculated_pattern.display_offset = new_offset
    
    # this observes the phase & marker models for deletion, if it is inside this specimen, it is removed as well.
    child_observer = None   
    class ChildObserver(Observer):
        specimen = None
        
        def __init__(self, specimen, *args, **kwargs):
            self.specimen = specimen
            Observer.__init__(self, *args, **kwargs)
        
        @Observer.observe("removed", signal=True)
        def notification(self, model, prop_name, info):
            #model         = child model that we're observing
            #self.specimen = specimen that is observing the model
            if isinstance(model, Marker):
                self.specimen._del_child_model(model, '_data_markers', 'data_marker_removed', remove='remove_item')
                #self.specimen.del_marker(model)
            if isinstance(model, Phase):
                self.specimen.del_phase(model)
    
    _data_phases = []
    @Model.getter("data_phases")
    def get_data_phases(self, prop_name):
        return self._data_phases
        
    _data_markers = None
    @Model.getter("data_markers")
    def get_data_markers(self, prop_name):
        return self._data_markers
        
    def _add_child_model(self, model, prop_name, signal_name):
        if not model in getattr(self, prop_name):
            if self.child_observer == None:
                self.child_observer = Specimen.ChildObserver(self)
            self.child_observer.observe_model(model)
            getattr(self, prop_name).append(model)
            getattr(self, signal_name).emit(model)
            
    def _del_child_model(self, model, prop_name, signal_name, remove="remove"):
        if model in getattr(self, prop_name):
            if self.child_observer != None:
                self.child_observer.relieve_model(model)
            else:
                self.child_observer = Specimen.ChildObserver(self)
            getattr(getattr(self, prop_name), remove)(model)
            getattr(self, signal_name).emit(model)
        
    data_phase_added = Signal()
    def add_phase(self, phase):
        self._add_child_model(phase, '_data_phases', 'data_phase_added')
    
    data_phase_removed = Signal()
    def del_phase(self, phase):
        self._del_child_model(phase, '_data_phases', 'data_phase_removed')
        
    data_marker_added = Signal()
    def add_marker(self, marker):
        marker.parent = self
        self._add_child_model(marker, '_data_markers', 'data_marker_added')
        if self.__pctrl__:
            self.__pctrl__.register(marker, "on_update_plot", last=True)
    
    data_marker_removed = Signal()
    def del_marker(self, marker):
        marker.parent = None
    
    def __init__(self, data_name="", data_sample="", data_sample_length=3.0,
                 display_calculated=True, display_experimental=True, display_phases=False,
                 data_experimental_pattern = None, data_calculated_pattern = None, data_markers = None,
                 phase_indeces=None, calc_color=None, exp_color=None, 
                 inherit_calc_color=True, inherit_exp_color=True, parent=None):
        ChildModel.__init__(self, parent=parent)
        Observable.__init__(self)
        Storable.__init__(self)
        
        self.data_name = data_name
        self.data_sample = data_sample
        self.data_sample_length = data_sample_length

        self._calc_color = calc_color or self.calc_color
        self._exp_color = exp_color or self.exp_color
        
        self.inherit_calc_color = inherit_calc_color
        self.inherit_exp_color = inherit_exp_color
        
        self.data_calculated_pattern = data_calculated_pattern or XYData("Calculated Profile", color=self.calc_color)
        self.data_experimental_pattern = data_experimental_pattern or XYData("Experimental Profile", color=self.exp_color)
        self._data_markers =  data_markers or ObjectListStore(Marker)
        
        self.display_calculated = display_calculated
        self.display_experimental = display_experimental
        self.display_phases = display_phases
        
        #Resolve JSON indeces:
        if phase_indeces is not None and self.parent is not None:
            self._data_phases = [self.parent.data_phases.get_user_data_from_index(index) for index in phase_indeces]
    
    def __str__(self):
        return "<Specimen %s(%s)>" % (self.data_name, repr(self))
    
    def json_properties(self):
        retval = Storable.json_properties(self)
        retval["phase_indeces"] = [self.parent.data_phases.index(phase) for phase in self.data_phases]
        retval["calc_color"] = self._calc_color
        retval["exp_color"] = self._exp_color
        return retval
    
    @staticmethod          
    def from_json(**kwargs):
        if "data_calculated_pattern" in kwargs:
            kwargs["data_calculated_pattern"] = PyXRDDecoder.__pyxrd_decode__(kwargs["data_calculated_pattern"])
        if "data_experimental_pattern" in kwargs:
            kwargs["data_experimental_pattern"] = PyXRDDecoder.__pyxrd_decode__(kwargs["data_experimental_pattern"])
        if "data_markers" in kwargs:
            kwargs["data_markers"] = PyXRDDecoder.__pyxrd_decode__(kwargs["data_markers"])
        specimen = Specimen(**kwargs)
        for marker in specimen.data_markers._model_data:
            marker.parent = specimen
        return specimen
        
    @staticmethod  
    def from_experimental_data(parent, data, format="DAT", filename=""):
        specimen = Specimen(parent=parent)
        
        if format=="DAT":        
            header, data = data.split("\n", 1)
            
            specimen.data_experimental_pattern.load_data(data, format=format, has_header=False)
            specimen.data_name = os.path.basename(filename)
            specimen.data_sample = header
            
        elif format=="BIN":
            import struct
            
            f = open(data, 'rb')
            f.seek(146)
            specimen.data_sample = str(f.read(16))
            specimen.data_name = os.path.basename(data)
            specimen.data_experimental_pattern.load_data(data=f, format=format)
            f.close()
        
        return specimen
        
    def on_update_plot(self, figure, axes, pctrl):       
        if self.display_experimental:
            self.data_experimental_pattern.on_update_plot(figure, axes, pctrl)
        if self.display_calculated:
            self.calculate_pattern(silent=True)
            self.data_calculated_pattern.on_update_plot(figure, axes, pctrl)        
        pctrl.update_lim()
        
    def calculate_pattern(self,steps=200, use_exp=False, silent=False, return_all=False):
        #TODO TEST THIS:
        
        if len(self._data_phases) == 0:
            self.data_calculated_pattern.xy_data.clear()
        else:
            #todo part of these things should be calculated in the Goniometer and only changed when needed (e.g. the normal range)
            S = self.parent.data_goniometer.get_S()
            S1S2 = self.parent.data_goniometer.data_soller1 * self.parent.data_goniometer.data_soller2
            l = self.parent.data_goniometer.data_lambda
            L_Rta =  self.data_sample_length / (self.parent.data_goniometer.data_radius * tan(radians(self.parent.data_goniometer.data_divergence)))
            min_theta = radians(self.parent.data_goniometer.data_min_2theta*0.5)
            max_theta = radians(self.parent.data_goniometer.data_max_2theta*0.5)
            delta_theta = float(max_theta - min_theta) / float(steps-1)
            
            if not use_exp:
                theta_range = [ (min_theta + delta_theta * float(step)) for step in range(0,steps-1) ]
            else:
                theta_range = [ radians(twotheta*0.5) for twotheta in self.data_experimental_pattern.xy_data._model_data_x]
            stl_range = [ sin(theta)/l for theta in theta_range]
            tstl_range = zip(theta_range, stl_range)
            
            intensity_range = []
            lpf_range = []
            iff_range = []
            stf_range = []            
            
            Imax = 0
            Imin = 0
            for theta, stl in tstl_range:
                lpf, iff, stf, I = 0, 0, 0, 0
                for phase in self._data_phases:
                    _lpf, _iff, _stf, _I = phase.get_relative_diffracted_intensity(theta, stl, S, S1S2)
                    I += _I
                    lpf += _lpf
                    iff += _iff
                    stf += _stf
                
                #correction for sample length:
                I = I * min(sin(theta) * L_Rta,1)
                    
                Imax = max(I, Imax)
                Imin = min(I, Imin)
                intensity_range.append(I)
                lpf_range.append(lpf)
                iff_range.append(iff)
                stf_range.append(stf)
            
            self.data_calculated_pattern.clear(update=False)
            
            for I, t in zip(intensity_range, theta_range):
                if (Imax - Imin) != 0:
                    I = I / Imax #NORMALISATION 
                self.data_calculated_pattern.xy_data.append(degrees(t)*2, I)
            self.data_calculated_pattern.update_data()
            
            if return_all:
                return (theta_range, lpf_range, iff_range, stf_range, intensity_range)
            else:
                return (theta_range, intensity_range)
        
    def auto_add_peaks(self, threshold):
        print "AUTO ADD PEAKS"
        
        xy = self.data_experimental_pattern.xy_data              
        maxtab, mintab = peakdetect(xy._model_data_y, xy._model_data_x, 5, threshold)
        
        mpositions = []
        for marker in self.data_markers._model_data:
            mpositions.append(marker.data_position)

        i = 1
        for x, y in maxtab:
            if not x in mpositions:
                new_marker = Marker("Peak %d - %.2f" % (i, x), parent=self, data_position=x, data_style="dotted" ,data_base=1)
                self.add_marker(new_marker)
            i += 1
    pass #end of class
    
class ThresholdSelector(ChildModel, Observable):
    
    __observables__ = [ "pattern", "max_threshold", "steps", "sel_threshold", "threshold_plot_data", "sel_num_peaks" ]
    
    _pattern = "exp"
    _patterns = { "exp": "Experimental Pattern", "calc": "Calculated Pattern" }
    @Model.getter("pattern")
    def get_pattern(self, prop_name):
        return self._pattern
    @Model.setter("pattern")
    def set_pattern(self, prop_name, value):
        if value in self._patterns: 
            self._pattern = value      
        else:
            raise ValueError, "'%s' is not a valid value for pattern!" % value
            self.update_threshold_plot_data()
    
    _max_threshold = 0.32
    @Model.getter("max_threshold")
    def get_max_threshold(self, prop_name):
        return self._max_threshold
    @Model.setter("max_threshold")
    def set_max_threshold(self, prop_name, value):
        value = min(max(0, float(value)), 1) #set some bounds
        if value != self._max_threshold:
            self._max_threshold = value
            self.update_threshold_plot_data()
            
    _steps = 20
    @Model.getter("steps")
    def get_steps(self, prop_name):
        return self._steps
    @Model.setter("steps")
    def set_steps(self, prop_name, value):
        value = min(max(3, value), 50) #set some bounds
        if value != self._steps:
            self._steps = value
            self.update_threshold_plot_data()
            
    _sel_threshold = 0.1
    sel_num_peaks = 0
    @Model.getter("sel_threshold")
    def get_sel_threshold(self, prop_name):
        return self._sel_threshold
    @Model.setter("sel_threshold")
    def set_sel_threshold(self, prop_name, value):
        if value != self._sel_threshold:
            self._sel_threshold = value
            deltas, numpeaks = self.threshold_plot_data
            self.sel_num_peaks = int(interpolate(zip(deltas, numpeaks), self._sel_threshold))
    
    threshold_plot_data = None
   
    
    def __init__(self, max_threshold=None, steps=None, sel_threshold=None, parent=None):
        ChildModel.__init__(self, parent=parent)
        Observable.__init__(self)
        
        self.max_threshold = max_threshold or self.max_threshold
        self.steps = steps or self.steps
        self.sel_threshold = sel_threshold or self.sel_threshold
        
        self.update_threshold_plot_data()
    
    def _get_xy(self):
        if self._pattern == "exp":
            return self.parent.data_experimental_pattern.xy_data
        elif self._pattern == "calc":
            return self.parent.data_calculated_pattern.xy_data
    
    def update_threshold_plot_data(self):
        if self.parent != None:
            xy = self._get_xy()
            
            length = len(xy._model_data_x)
            resolution = length / (xy._model_data_x[-1] - xy._model_data_x[0])
            delta_angle = 0.05
            window = int(delta_angle * resolution)
            window += (window % 2)*2
            
            steps = max(self.steps, 2) - 1
            factor = self.max_threshold / steps

            deltas = [i*factor for i in range(0, self.steps)]
            
            numpeaks = []
            maxtabs, mintabs = multi_peakdetect(xy._model_data_y, xy._model_data_x, 5, deltas)
            for maxtab, mintab in zip(maxtabs, mintabs):
                numpeak = len(maxtab)
                numpeaks.append(numpeak)
            numpeaks = map(float, numpeaks)
            
            #update plot:
            self.threshold_plot_data = (deltas, numpeaks)
            
            #update auto selected threshold:
            ln = 4
            max_ln = len(deltas)
            stop = False
            while not stop:
                x = deltas[0:ln]
                y = numpeaks[0:ln]
                slope, intercept, R, p_value, std_err = stats.linregress(x,y)
                ln += 1
                if abs(R) < 0.95 or ln >= max_ln:
                    stop = True
                peak_x = -intercept / slope                

            self.sel_threshold = peak_x
            
class Marker(ChildModel, Observable, Storable):
    
    __columns__ = [
        ('data_label', str),
        ('data_visible', bool),
        ('data_position', float),
        ('data_color', str),
        ('data_base', bool),
        ('data_angle', float),
        ('inherit_angle', bool),
        ('data_style', str)
    ]
    __observables__ = [ key for key, val in __columns__]
    __storables__ = __observables__

    data_label = ""
    data_visible = True
    data_position = 0.0
    data_color = "#000000"

    _inherit_angle = True
    @Model.getter("inherit_angle")
    def get_inherit_angle(self, prop_name):
        return self._inherit_angle
    @Model.setter("inherit_angle")
    def set_inherit_angle(self, prop_name, value):
        if value != self._inherit_angle:
            self._inherit_angle = value
            if self._text!=None:
                self._text.set_rotation(90-self.data_angle)
            
    _data_angle = 0.0
    @Model.getter("data_angle")
    def get_data_angle(self, prop_name):
        if self.inherit_angle and self.parent!=None and self.parent.parent!=None:
            return self.parent.parent.display_marker_angle
        else:
            return self._data_angle
    @Model.setter("data_angle")
    def set_data_angle(self, prop_name, value):
        if value != self._data_angle:
            self._data_angle = value
            if self._text!=None:
                self._text.set_rotation(90-self.data_angle)
    
    _data_base = 0
    _data_bases = { 0: "X-axis", 1: "Experimental profile", 2: "Calculated profile", 3: "Lowest of both", 4: "Highest of both" }
    @Model.getter("data_base")
    def get_data_base(self, prop_name):
        return self._data_base
    @Model.setter("data_base")
    def set_data_base(self, prop_name, value):
        value = int(value)
        if value in self._data_bases: 
            self._data_base = value      
        else:
            raise ValueError, "'%s' is not a valid value for a marker base!" % value
    
    
    _data_style = "solid"
    _data_styles = { "solid": "Solid", "dashed": "Dash", "dotted": "Dotted", "dashdot": "Dash-Dotted" }
    @Model.getter("data_style")
    def get_data_style(self, prop_name):
        return self._data_style
    @Model.setter("data_style")
    def set_data_style(self, prop_name, value):
        if value in self._data_styles: 
            self._data_style = value      
        else:
            raise ValueError, "'%s' is not a valid value for a marker style!" % value
    
    def __init__(self, data_label="", data_visible=True, data_position=0.0, data_color="#000000", data_base=0,
                 data_angle=0.0, inherit_angle=True, data_style="solid", parent=None):
        ChildModel.__init__(self, parent=parent)
        Observable.__init__(self)
        Storable.__init__(self)
        
        self.data_label = data_label
        self.data_visible = data_visible
        self.data_position = data_position
        self.data_color = data_color
        self.data_base = data_base
        self.inherit_angle = inherit_angle
        self.data_angle = data_angle
        self.data_style = data_style
        
    def get_ymin(self):
        return min(self.get_y(self.parent.data_experimental_pattern.line), 
                   self.get_y(self.parent.data_calculated_pattern.line))
    def get_ymax(self):
        return max(self.get_y(self.parent.data_experimental_pattern.line), 
                   self.get_y(self.parent.data_calculated_pattern.line))   
    def get_y(self, line):
        x_data, y_data = line.get_data()
        if len(x_data) > 0:
            return np.interp(self.data_position, x_data, y_data)
        else:
            return 0
    
    _vline = None
    _text = None
    
    def update_text(self, figure, axes):
        kws = dict(text=self.data_label,
                   x=self.data_position, y=0.8,
                   clip_on=False,
                   transform=transforms.blended_transform_factory(axes.transData, figure.transFigure),
                   horizontalalignment="left", verticalalignment="center",
                   rotation=(90-self.data_angle), rotation_mode="anchor",
                   color=self.data_color)
        
        if self._text == None:
            self._text = Text(**kws)
        else:
            for key in kws:
                getattr(self._text, "set_%s"%key)(kws[key])
        if not self._text in axes.get_children():
            axes.add_artist(self._text)
                
                
    
    def update_vline(self, figure, axes):
        y = 0
        if int(self.data_base) == 1:
            y = self.get_y(self.parent.data_experimental_pattern.line)
        elif self.data_base == 2:
            y = self.get_y(self.parent.data_calculated_pattern.line)
        elif self.data_base == 3:   
            y = self.get_ymin()
        elif self.data_base == 4:
            y = self.get_ymax()
            
        xmin, xmax = axes.get_xbound()
        ymin, ymax = axes.get_ybound()

        # We need to strip away the units for comparison with
        # non-unitized bounds
        scalex = (self.data_position<xmin) or (self.data_position>xmax)
        trans = transforms.blended_transform_factory(axes.transData, axes.transAxes)
        y = (y - ymin) / (ymax - ymin)
            
        if self._vline == None:
            self._vline = matplotlib.lines.Line2D([self.data_position,self.data_position], [y,1] , transform=trans, color=self.data_color, ls=self.data_style)
            self._vline.y_isdata = False
        else:
            self._vline.set_xdata(np.array([self.data_position,self.data_position]))
            self._vline.set_ydata(np.array([y,1]))
            self._vline.set_transform(trans)
            self._vline.set_color(self.data_color)
            self._vline.set_linestyle(self.data_style)
            
        if not self._vline in axes.get_lines():
            axes.add_line(self._vline)
            axes.autoscale_view(scalex=scalex, scaley=False)
    
    def on_update_plot(self, figure, axes, pctrl):
        self.update_vline(figure, axes)
        self.update_text(figure, axes)
               
    def get_nm_position(self):
        if self.data_position != 0:
            return self.parent.parent.data_goniometer.data_lambda / (2.0*sin(radians(self.data_position/2.0)))
        else:
            return 0.0
        
    def set_nm_position(self, position):
        t = 0.0
        if position != 0: 
            t = degrees(asin(max(-1.0, min(1.0, self.parent.parent.data_goniometer.data_lambda/(2.0*position)))))*2.0
        self.data_position = t

    @staticmethod          
    def from_json(**kwargs):
        return Marker(**kwargs)

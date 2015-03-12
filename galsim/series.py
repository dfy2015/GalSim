# Copyright (c) 2012-2014 by the GalSim developers team on GitHub
# https://github.com/GalSim-developers
#
# This file is part of GalSim: The modular galaxy image simulation toolkit.
# https://github.com/GalSim-developers/GalSim
#
# GalSim is free software: redistribution and use in source and binary forms,
# with or without modification, are permitted provided that the following
# conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions, and the disclaimer given in the accompanying LICENSE
#    file.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions, and the disclaimer given in the documentation
#    and/or other materials provided with the distribution.
#
"""@file series.py
Definitions for Galsim Series class and subclasses.
"""

import galsim
import numpy as np
import copy
import math
import operator
from itertools import product, combinations, count


class Series(object):
    # Share caches among all subclasses of Series
    _cache = {}
    _kcache = {}
    _root = None
    _kroot = None

    def __init__(self, maxcache=100):
        """Abstract base class for GalSim profiles represented as a series of basis profiles.
        Generally, coefficients of the basis profiles can be manipulated to set parameters of the 
        series profile, such as size and ellipticity for SpergelSeries and MoffatSeries, or
        wavefront expansion coefficients for LinearOpticalSeries.  This allows one to rapidly
        create images with arbitrary values of these parameters by forming linear combinations of
        images of the basis profiles, which can be precomputed and cached in memory.  The
        convolution of two series objects can also be rapidly computed once the convolution of each
        term in the Cartesian product of each series' basis profiles is computed, drawn to an image,
        and cached.

        One drawback for Series objects is that a cache is only good for a single combination of
        image parameters, such as the shape and scale.  If you want to draw a new image at a
        different scale or with a different shape, the precomputation of the basis profile images
        will be done again and cached for future use.

        The first Series object created can set the `maxcache` keyword, which sets how many Series
        objects will be cached in memory before new cache entries begin to over-write earlier cache
        entries.  This may be important to conserve RAM, as its not too hard to create caches that
        occupy 10s to 100s (or more!) MB of memory.  You can check the current state of the cache
        with the Series.inspectCache() method.
        """
        # Initialize caches
        if self._root is None:
            # Steal some ideas from http://code.activestate.com/recipes/577970-simplified-lru-cache/
            # Note that self._root = ... doesn't work since this will set [subclass]._root instead
            # of Series._root.
            # Link layout:       [PREV, NEXT, KEY, RESULT]
            Series._root = root = [None, None, None, None]
            cache = self._cache
            last = root
            for i in range(maxcache):
                key = object()
                cache[key] = last[1] = last = [last, root, key, None]
            root[0] = last
            # And similarly for Fourier-space cache
            Series._kroot = kroot = [None, None, None, None]
            kcache = self._kcache
            klast = kroot
            for i in range(maxcache):
                key = object()
                kcache[key] = klast[1] = klast = [klast, kroot, key, None]
            kroot[0] = last
            
    # TODO: could probably combine _basisCube and _basisKCube with the addition of a few helper
    # methods
            
    def _basisCube(self, key):
        # Query the cache of image cubes and find the one corresponding to a particular Series object
        # with particular image settings.  If it's not present in the cache, then create it.
        # `key` here is a 3-tuple with indices:
        #       0: Class-specific parameters
        #       1: args to be used in drawImage
        #       2: kwargs to be used in drawImage, as a tuple of tuples to make it hashable.
        #          The first item of each interior tuple is the kwarg name as a string, and the
        #          second item is the associated value.
        cache = Series._cache
        root = Series._root
        link = cache.get(key)
        if link is not None:
            link_prev, link_next, _, result = link
            link_prev[1] = link_next
            link_next[0] = link_prev
            last = root[0]
            last[1] = root[0] = link
            link[0] = last
            link[1] = root
            return result
        # Didn't find the cube we were looking for, so create it.
        series_idx, args, kwargs = key
        kwargs = dict(kwargs)
        objs = self._getBasisFuncs()
        im0 = objs[0].drawImage(*args, **kwargs)
        shape = im0.array.shape
        # It's faster to store the stack of basis images as a series of 1D vectors (i.e. a 2D
        # numpy array instead of a cube (or rectangular prism I guess...))
        # This makes the linear combination step a matrix multiply, which is like lightning.
        # I still think of this data structure as a cube though, so that's what I'm calling it.
        cube = np.empty((len(objs), shape[0]*shape[1]), dtype=im0.array.dtype)
        for i, obj in enumerate(objs):
            cube[i] = obj.drawImage(*args, **kwargs).array.ravel()
        root[2] = key
        # Need to store the image shape here so we can eventually turn 1D image vector back into a
        # 2D image.
        root[3] = (cube, shape)
        oldroot = root
        root = Series._root = root[1]
        root[2], oldkey = None, root[2]
        root[3], oldvalue = None, root[3]
        del cache[oldkey]
        cache[key] = oldroot
        return cube, shape

    def _basisKCube(self, key):
        # Query the cache of kimage cubes and find the one corresponding to a particular Series
        # object with particular image settings.  If it's not present in the cache, then create it.
        # `key` here is a 3-tuple with indices:
        #       0: Class-specific parameters
        #       1: args to be used in drawKImage
        #       2: kwargs to be used in drawKImage, as a tuple of tuples to make it hashable.
        #          The first item of each interior tuple is the kwarg name as a string, and the
        #          second item is the associated value.
        cache = Series._kcache
        root = Series._kroot
        link = cache.get(key)
        if link is not None:
            link_prev, link_next, _, result = link
            link_prev[1] = link_next
            link_next[0] = link_prev
            last = root[0]
            last[1] = root[0] = link
            link[0] = last
            link[1] = root
            return result
        # Didn't find the cube we were looking for, so create it.
        series_idx, args, kwargs = key
        kwargs = dict(kwargs)
        objs = self._getBasisFuncs()
        re0, im0 = objs[0].drawKImage(*args, **kwargs)
        shape = im0.array.shape
        # It's faster to store the stack of basis images as a series of 1D vectors (i.e. a 2D
        # numpy array instead of a cube (or rectangular prism I guess...))
        # This makes the linear combination step a matrix multiply, which is like lightning.
        # I still think of this data structure as a cube though, so that's what I'm calling it.
        recube = np.empty((len(objs), shape[0]*shape[1]), dtype=im0.array.dtype)
        imcube = np.empty_like(recube)
        for i, obj in enumerate(objs):
            tmp = obj.drawKImage(*args, **kwargs)
            recube[i] = tmp[0].array.ravel()
            imcube[i] = tmp[1].array.ravel()
        root[2] = key
        # Need to store the image shape here so we can eventually turn 1D kimage vectors back into 
        # 2D kimages.
        root[3] = (recube, imcube, shape)
        oldroot = root
        root = Series._kroot = root[1]
        root[2], oldkey = None, root[2]
        root[3], oldvalue = None, root[3]
        del cache[oldkey]
        cache[key] = oldroot
        return recube, imcube, shape

    def drawImage(self, *args, **kwargs):
        """Draw a Series object by forming the appropriate linear combination of basis profile
        images.  This method will search the Series cache to see if the basis images for this
        object already exist, and if not then create and cache them.  Note that a separate cache is
        created for each combination of image parameters (such as shape, wcs, scale, etc.) and also
        certain profile parameters (such as the SpergelSeries `nu` parameter or the MoffatSeries
        `beta` parameter.)

        See GSObject.drawImage() for a description of available arguments for this method.
        """
        key = (self._series_idx(), args, tuple(sorted(kwargs.items())))
        cube, shape = self._basisCube(key)
        coeffs = np.array(self._getCoeffs(), dtype=cube.dtype)
        im = np.dot(coeffs, cube).reshape(shape)
        return galsim.Image(im)
        
    def drawKImage(self, *args, **kwargs):
        """Draw the Fourier-space image of a Series object by forming the appropriate linear
        combination of basis profile Fourier-space images.  This method will search the Series cache
        to see if the basis images for this object already exist, and if not then create and cache
        them.  Note that a separate cache is created for each combination of image parameters (such
        as shape, wcs, scale, etc.) and also certain profile parameters (such as the SpergelSeries
        `nu` parameter or the MoffatSeries `beta` parameter.)

        See GSObject.drawKImage() for a description of available arguments for this method.
        """
        key = (self._series_idx(), args, tuple(sorted(kwargs.items())))
        recube, imcube, shape = self._basisKCube(key)
        coeffs = np.array(self._getCoeffs(), dtype=recube.dtype)
        reim = np.dot(coeffs, recube).reshape(shape)
        imim = np.dot(coeffs, imcube).reshape(shape)
        return galsim.Image(reim), galsim.Image(imim)

    def kValue(self, *args, **kwargs):
        """Calculate the value of the Fourier-space image of this Series object at a particular
        coordinate by forming the appropriate linear combination of Fourier-space values of basis
        profiles.

        This method does not use the Series cache.

        See GSObject.kValue() for a description of available arguments for this method.
        """
        kvals = [obj.kValue(*args, **kwargs) for obj in self._getBasisFuncs()]
        coeffs = self._getCoeffs()
        return np.dot(kvals, coeffs)

    def xValue(self, *args, **kwargs):
        """Calculate the value of the image of this Series object at a particular coordinate by
        forming the appropriate linear combination of values of basis profiles.

        This method does not use the Series cache.

        See GSObject.xValue() for a description of available arguments for this method.
        """
        xvals = [obj.xValue(*args, **kwargs) for obj in self._getBasisFuncs()]
        coeffs = self._getCoeffs()
        return np.dot(xvals, coeffs)
        
    @classmethod
    def inspectCache(self):
        """ Report details of the Series cache, including the number of cached profiles and an
        estimate of the memory footprint of the cache.
        """
        i=0
        ik=0
        mem=0
        for k,v in self._cache.iteritems():
            if not isinstance(k, tuple):
                continue
            i += 1
            print
            print "Cached image object: "
            print v[2]
            print "# of basis images: {:0}".format(v[3][0].shape[0])
            print "images are {:0} x {:1} pixels".format(*v[3][1])
            mem += v[3][0].nbytes
            if k in self._kcache:
                v = self._kcache[k]
                ik += 1
                print
                print "Cached kimage object: "
                print v[2]
                print "# of basis kimages: {:0}".format(v[3][0].shape[0])
                print "kimages are {:0} x {:1} pixels".format(*v[3][2])
                mem += v[3][0].nbytes
                mem += v[3][1].nbytes
        print
        print "Found {:0} image caches".format(i)
        print "Found {:0} kimage caches".format(ik)
        print "Cache occupies ~{:0} bytes".format(mem)

    def _getCoeffs(self):
        raise NotImplementedError("subclasses of Series must define _getCoeffs() method")

    def _getBasisFuncs(self):
        raise NotImplementedError("subclasses of Series must define _getBasisFuncs() method")

    def _series_idx(self):
        raise NotImplementedError("subclasses of Series must define _series_idx() method")

        
class SeriesConvolution(Series):
    def __init__(self, *args, **kwargs):
        """A Series profile representing the convolution of multiple Series objects and/or
        GSObjects.
        """
        # First check for number of arguments != 0
        if len(args) == 0:
            # No arguments. Could initialize with an empty list but draw then segfaults. Raise an
            # exception instead.
            raise ValueError("Must provide at least one Series or GSObject")
        elif len(args) == 1:
            if isinstance(args[0], (Series, galsim.GSObject)):
                args = [args[0]]
            elif isinstance(args[0], list):
                args = args[0]
            else:
                raise TypeError(
                    "Single input argument must be a Series or GSObject or a list of them.")
        # Check kwargs
        self.gsparams = kwargs.pop("gsparams", None)
        # Make sure there is nothing left in the dict.
        if kwargs:
            raise TypeError("Got unexpected keyword argument(s): %s"%kwargs.keys())
        # Unpack any Convolution of Convolutions.
        self.objlist = []
        for obj in args:
            if isinstance(obj, SeriesConvolution):
                self.objlist.extend([o for o in obj.objlist])
            else:
                self.objlist.append(obj)

        # Magically transform GSObjects into super-simple Series objects
        for obj in self.objlist:
            if isinstance(obj, galsim.GSObject):
                obj._getCoeffs = lambda : [1.0]
                obj._getBasisFuncs = lambda :[obj]
                # This could be better...  Currently this will create two entries in the cache if
                # separate-in-memory, but identical-in-value GSObjects are convolved with the same
                # Series object.  One could imagine making GSObjects hashable and defining their
                # hashes via their values (e.g., scale_radius, affine transformations, interpolated
                # arrays, etc.).
                obj._series_idx = lambda : id(obj)

        super(SeriesConvolution, self).__init__()

    def _getCoeffs(self):
        # This is a faster, but somewhat more opaque version of
        # return np.multiply.reduce([c for c in product(*[obj._getCoeffs()
        #                                                 for obj in self.objlist])], axis=1)
        # The above use to be the limiting step in some convolutions.  The new version is
        # ~100 times faster, which doesn't mean the convolution is 100 times faster, but now
        # another piece of code is the rate-limiting-step.
        return np.multiply.reduce(np.ix_(*[np.array(obj._getCoeffs())
                                           for obj in self.objlist])).ravel()

    def _getBasisFuncs(self):
        return [galsim.Convolve(*o) for o in product(*[obj._getBasisFuncs()
                                                       for obj in self.objlist])]

    def _series_idx(self):
        out = [self.__class__]
        out.extend([o._series_idx() for o in self.objlist])
        return tuple(out)

    
class SpergelSeries(Series):
    def __init__(self, nu, jmax, dlnr=None, half_light_radius=None, scale_radius=None,
                 flux=1.0, gsparams=None):
        self.nu = nu
        self.jmax = jmax
        if dlnr is None:
            dlnr = np.log(1.3)
        self.dlnr = dlnr
        if half_light_radius is not None:
            prof = galsim.Spergel(nu=nu, half_light_radius=half_light_radius)
            scale_radius = prof.getScaleRadius()
        self.scale_radius = scale_radius
        self.flux = flux
        self.gsparams = gsparams

        # Store transformation relative to scale_radius=1.
        self._A = np.matrix(np.identity(2)*self.scale_radius, dtype=float)
        super(SpergelSeries, self).__init__()

    def _getCoeffs(self):
        ellip, phi0, scale_radius, Delta = self._decomposeA()
        coeffs = []
        for j in xrange(self.jmax+1):
            for q in xrange(-j, j+1):
                coeff = 0.0
                for m in range(abs(q), j+1):
                    if (m+q)%2 == 1:
                        continue
                    n = (q+m)/2
                    num = (Delta-1.0)**m
                    # Have to catch 0^0=1 situations...
                    if not (Delta == 0.0 and j==m):
                        num *= Delta**(j-m)
                    if not (ellip == 0.0 and m==0):
                        num *= ellip**m
                    den = 2**(m-1) * math.factorial(j-m) * math.factorial(m-n) * math.factorial(n)
                    coeff += num/den
                if q > 0:
                    coeff *= self.flux * math.cos(2*q*phi0)
                elif q < 0:
                    coeff *= self.flux * math.sin(2*q*phi0)
                else:
                    coeff *= self.flux * 0.5
                coeffs.append(coeff)
        return coeffs
                
    def _getBasisFuncs(self):
        ellip, phi0, scale_radius, Delta = self._decomposeA()
        objs = []
        for j in xrange(self.jmax+1):
            for q in xrange(-j, j+1):
                objs.append(Spergelet(nu=self.nu, scale_radius=scale_radius,
                                      j=j, q=q, gsparams=self.gsparams))
        return objs

    def _series_idx(self):
        _, _, scale_radius, _ = self._decomposeA()
        return (self.__class__, self.nu, self.jmax, scale_radius)
    
    def copy(self):
        """Returns a copy of an object.  This preserves the original type of the object."""
        cls = self.__class__
        ret = cls.__new__(cls)
        for k, v in self.__dict__.iteritems():
            ret.__dict__[k] = copy.copy(v)
        return ret

    def _applyMatrix(self, J):
        ret = self.copy()
        ret._A *= J
        if hasattr(ret, 'ellip'): # reset lazy affine transformation evaluation
            del ret.ellip
        return ret

    def dilate(self, scale):
        E = np.diag([scale, scale])
        return self._applyMatrix(E)

    def shear(self, *args, **kwargs):
        if len(args) == 1:
            if kwargs:
                raise TypeError("Gave both unnamed and named arguments!")
            if not isinstance(args[0], galsim.Shear):
                raise TypeError("Unnamed argument is not a Shear!")
            shear = args[0]
        elif len(args) > 1:
            raise TypeError("Too many unnamed arguments!")
        elif 'shear' in kwargs:
            shear = kwargs.pop('shear')
            if kwargs:
                raise TypeError("Too many kwargs provided!")
        else:
            shear = galsim.Shear(**kwargs)
        return self._applyMatrix(shear._shear.getMatrix())

    def rotate(self, theta):
        cth = math.cos(theta.rad())
        sth = math.sin(theta.rad())
        R = np.matrix([[cth, -sth],
                       [sth,  cth]],
                      dtype=float)
        return self._applyMatrix(R)

    def _decomposeA(self):
        if not hasattr(self, 'ellip'):
            A = self._A
            a = A[0,0]
            b = A[0,1]
            c = A[1,0]
            d = A[1,1]
            mu = math.sqrt(a*d-b*c)
            phi0 = math.atan2(c-b, a+d)
            beta = math.atan2(b+c, a-d)+phi0
            eta = math.acosh(0.5*((a-d)**2 + (b+c)**2)/mu**2 + 1.0)

            # print "mu: {}".format(mu)
            # print "phi0: {}".format(phi0)
            # print "beta: {}".format(beta)
            # print "eta: {}".format(eta)

            ellip = galsim.Shear(eta1=eta).e1
            r0 = mu/np.sqrt(np.sqrt(1.0 - ellip**2))
            # find the nearest r_i:
            f, i = np.modf(np.log(r0)/self.dlnr)
            # deal with negative logs
            if f < 0.0:
                f += 1.0
                i -= 1
            # if f > 0.5, then round down from above
            if f > 0.5:
                f -= 1.0
                i += 1
            scale_radius = np.exp(self.dlnr*i)
            Delta = 1.0 - (r0/scale_radius)**2
            self.ellip = ellip
            self.phi0 = phi0+beta/2
            self.scale_radius = scale_radius
            self.Delta = Delta
        return self.ellip, self.phi0, self.scale_radius, self.Delta
        
        
class Spergelet(galsim.GSObject):
    """A basis function in the Taylor series expansion of the Spergel profile.

    @param nu               The Spergel index, nu.
    @param scale_radius     The scale radius of the profile.  Typically given in arcsec.
    @param j                Radial index.
    @param q                Azimuthal index.
    @param gsparams         An optional GSParams argument.  See the docstring for GSParams for
                            details. [default: None]
    """
    def __init__(self, nu, scale_radius, j, q, gsparams=None):
        galsim.GSObject.__init__(
            self, galsim._galsim.SBSpergelet(nu, scale_radius, j, q, gsparams=gsparams))

    def getNu(self):
        """Return the Spergel index `nu` for this profile.
        """
        return self.SBProfile.getNu()

    def getScaleRadius(self):
        """Return the scale radius for this Spergel profile.
        """
        return self.SBProfile.getScaleRadius()

    def getJQ(self):
        """Return the jq indices for this Spergelet.
        """
        return self.SBProfile.getJ(), self.SBProfile.getQ()


class MoffatSeries(Series):
    def __init__(self, beta, jmax, dlnr=None,
                 half_light_radius=None, scale_radius=None, fwhm=None,
                 flux=1.0, gsparams=None):
        self.beta = beta
        self.jmax = jmax
        if dlnr is None:
            dlnr = np.log(1.3)
        self.dlnr = dlnr
        if half_light_radius is not None:
            prof = galsim.Moffat(beta=beta, half_light_radius=half_light_radius)
            scale_radius = prof.getScaleRadius()
        elif fwhm is not None:
            prof = galsim.Moffat(beta=beta, fwhm=fwhm)
            scale_radius = prof.getScaleRadius()
        self.scale_radius = scale_radius
        self.flux = flux
        self.gsparams = gsparams

        # Store transformation relative to scale_radius=1.
        self._A = np.matrix(np.identity(2)*self.scale_radius, dtype=float)
        super(MoffatSeries, self).__init__()

    def _getCoeffs(self):
        ellip, phi0, scale_radius, Delta = self._decomposeA()
        coeffs = []
        for j in xrange(self.jmax+1):
            for q in xrange(-j, j+1):
                coeff = 0.0
                for m in range(abs(q), j+1):
                    if (m+q)%2 == 1:
                        continue
                    n = (q+m)/2
                    num = (1-Delta)**(m+1)
                    # Have to catch 0^0=1 situations...
                    if not (Delta == 0.0 and j==m):
                        num *= Delta**(j-m)
                    if not (ellip == 0.0 and m==0):
                        num *= ellip**m
                    den = 2**(m-1) * math.factorial(j-m) * math.factorial(m-n) * math.factorial(n)
                    coeff += num/den
                if q > 0:
                    coeff *= self.flux * math.sqrt(1.0 - ellip**2) * math.cos(2*q*phi0)
                elif q < 0:
                    coeff *= self.flux * math.sqrt(1.0 - ellip**2) * math.sin(2*q*phi0)
                else:
                    coeff *= self.flux * math.sqrt(1.0 - ellip**2) * 0.5
                coeffs.append(coeff)
        return coeffs
                
    def _getBasisFuncs(self):
        ellip, phi0, scale_radius, Delta = self._decomposeA()
        objs = []
        for j in xrange(self.jmax+1):
            for q in xrange(-j, j+1):
                objs.append(Moffatlet(beta=self.beta, scale_radius=scale_radius,
                                      j=j, q=q, gsparams=self.gsparams))
        return objs

    def _series_idx(self):
        _, _, scale_radius, _ = self._decomposeA()
        return (self.__class__, self.beta, self.jmax, scale_radius)
    
    def copy(self):
        """Returns a copy of an object.  This preserves the original type of the object."""
        cls = self.__class__
        ret = cls.__new__(cls)
        for k, v in self.__dict__.iteritems():
            ret.__dict__[k] = copy.copy(v)
        return ret

    def _applyMatrix(self, J):
        ret = self.copy()
        ret._A *= J
        if hasattr(ret, 'ellip'): # reset lazy affine transformation evaluation
            del ret.ellip
        return ret

    def dilate(self, scale):
        E = np.diag([scale, scale])
        return self._applyMatrix(E)

    def shear(self, *args, **kwargs):
        if len(args) == 1:
            if kwargs:
                raise TypeError("Gave both unnamed and named arguments!")
            if not isinstance(args[0], galsim.Shear):
                raise TypeError("Unnamed argument is not a Shear!")
            shear = args[0]
        elif len(args) > 1:
            raise TypeError("Too many unnamed arguments!")
        elif 'shear' in kwargs:
            shear = kwargs.pop('shear')
            if kwargs:
                raise TypeError("Too many kwargs provided!")
        else:
            shear = galsim.Shear(**kwargs)
        return self._applyMatrix(shear._shear.getMatrix())

    def rotate(self, theta):
        cth = math.cos(theta.rad())
        sth = math.sin(theta.rad())
        R = np.matrix([[cth, -sth],
                       [sth,  cth]],
                      dtype=float)
        return self._applyMatrix(R)

    def _decomposeA(self):
        if not hasattr(self, 'ellip'):
            A = self._A
            a = A[0,0]
            b = A[0,1]
            c = A[1,0]
            d = A[1,1]
            mu = math.sqrt(a*d-b*c)
            phi0 = math.atan2(c-b, a+d)
            beta = math.atan2(b+c, a-d)+phi0
            eta = math.acosh(0.5*((a-d)**2 + (b+c)**2)/mu**2 + 1.0)

            # print "mu: {}".format(mu)
            # print "phi0: {}".format(phi0)
            # print "beta: {}".format(beta)
            # print "eta: {}".format(eta)

            ellip = galsim.Shear(eta1=eta).e1
            r0 = mu/np.sqrt(np.sqrt(1.0 - ellip**2))
            # find the nearest r_i:
            f, i = np.modf(np.log(r0)/self.dlnr)
            # deal with negative logs
            if f < 0.0:
                f += 1.0
                i -= 1
            # if f > 0.5, then round down from above
            if f > 0.5:
                f -= 1.0
                i += 1
            scale_radius = np.exp(self.dlnr*i)
            Delta = 1.0 - (scale_radius/r0)**2
            self.ellip = ellip
            self.phi0 = phi0+beta/2
            self.scale_radius = scale_radius
            self.Delta = Delta
        return self.ellip, self.phi0, self.scale_radius, self.Delta

        
class Moffatlet(galsim.GSObject):
    """A basis function in the Taylor series expansion of the Moffat profile.

    @param beta             The Moffat index, beta.
    @param scale_radius     The scale radius of the profile.  Typically given in arcsec.
    @param j                Radial index.
    @param q                Azimuthal index.
    @param gsparams         An optional GSParams argument.  See the docstring for GSParams for
                            details. [default: None]
    """
    def __init__(self, beta, scale_radius, j, q, gsparams=None):
        galsim.GSObject.__init__(
            self, galsim._galsim.SBMoffatlet(beta, scale_radius, j, q, gsparams=gsparams))

    def getBeta(self):
        """Return the Moffat index `beta` for this profile.
        """
        return self.SBProfile.getBeta()

    def getScaleRadius(self):
        """Return the scale radius for this Moffat profile.
        """
        return self.SBProfile.getScaleRadius()

    def getJQ(self):
        """Return the jq indices for this Moffatlet.
        """
        return self.SBProfile.getJ(), self.SBProfile.getQ()

        
def nollZernikeDict(jmax):
    # Return dictionary for Noll Zernike convention taking index j -> n,m.
    ret = {}
    j=1
    for n in count():
        for m in xrange(n+1):
            if (m+n) % 2 == 1:
                continue
            if m == 0:
                ret[j] = (n, m)
                j += 1
            elif j % 2 == 0:
                ret[j] = (n, m)
                ret[j+1] = (n, -m)
                j += 2
            else:
                ret[j] = (n, -m)
                ret[j+1] = (n, m)
                j += 2
            if j > jmax:
                return ret
    return ret

nollZernike = nollZernikeDict(100)


class LinearOpticalSeries(Series):
    def __init__(self, lam_over_diam=None, lam=None, diam=None, flux=1.0,
                 tip=0., tilt=0., defocus=0., astig1=0., astig2=0.,
                 coma1=0., coma2=0., trefoil1=0., trefoil2=0., spher=0.,
                 aberrations=None, scale_unit=galsim.arcsec, gsparams=None):
        """ A series representation of the PSF generated by a series expansion of the entrance
        pupil wavefront to linear order.  Works by approximating exp(i phi) ~ 1 + i phi, where phi is
        the wavefront.  Should probably only use if the amplitude of the Zernike coefficients is less
        than 0.3 wavelengths or so, depending on the desired accuracy.
        """
        if lam_over_diam is not None:
            if lam is not None or diam is not None:
                raise TypeError("If specifying lam_over_diam, then do not specify lam or diam")
        else:
            if lam is None or diam is None:
                raise TypeError("If not specifying lam_over_diam, then specify lam AND diam")
                if isinstance(scale_unit, basestring):
                    scale_unit = galsim.angle.get_angle_unit(scale_unit)
                lam_over_diam = (1.e-9*lam/diam)*(galsim.radians/scale_unit)
        self.lam_over_diam = lam_over_diam
        self.flux = flux        

        if aberrations is None:
            # Repackage the aberrations into a single array.
            aberrations = np.zeros(12)
            aberrations[2] = tip
            aberrations[3] = tilt
            aberrations[4] = defocus
            aberrations[5] = astig1
            aberrations[6] = astig2
            aberrations[7] = coma1
            aberrations[8] = coma2
            aberrations[9] = trefoil1
            aberrations[10] = trefoil2
            aberrations[11] = spher
            # Clip at largest non-zero aberration (or 2)
            nz = aberrations.nonzero()[0]
            if len(nz) == 0:
                i = 2
            else:
                i = max([nz[-1]+1, 2])
            aberrations = aberrations[:i]
        else:
            # Aberrations were passed in, so check that there are the right number of entries.
            # Note that while we do have a lower limit here, there is no upper limit (in contrast
            # to OpticalPSF).
            if len(aberrations) <= 2:
                raise ValueError("Aberrations keyword must have length > 2")
            # Make sure no individual ones were passed in, since they will be ignored.
            if np.any(
                np.array([tip, tilt, defocus, astig1, astig2,
                          coma1, coma2, trefoil1, trefoil2, spher]) != 0):
                raise TypeError("Cannot pass in individual aberrations and array!")
        # Finally, just in case it was a tuple/list, make sure we end up with NumPy array:
        self.aberrations = np.array(aberrations) * 2.0 * np.pi

        def norm(n, m):
            if m==0:
                return np.sqrt(n+1)
            else:
                return np.sqrt(2*n+2)
            
        # Now separate into terms that are pure real and pure imag in the complex PSF
        self.realcoeffs = [1.0]
        self.imagcoeffs = []
        self.realindices = [(0,0)]
        self.imagindices = []
        for j, ab in enumerate(self.aberrations):
            if j < 2:
                continue
            n,m = nollZernike[j]
            ipower = (m+1)%4    
            if ipower == 0:
                self.realcoeffs.append(norm(n,m)*ab)
                self.realindices.append((n,m))
            elif ipower == 1:
                self.imagcoeffs.append(norm(n,m)*ab)
                self.imagindices.append((n, m))
            elif ipower == 2:
                self.realcoeffs.append(-norm(n,m)*ab)
                self.realindices.append((n,m))
            elif ipower == 3:
                self.imagcoeffs.append(-norm(n,m)*ab)
                self.imagindices.append((n, m))
            else:
                raise RuntimeError("What!?  How'd that happen?")
        # First do the square coefficients
        self.coeffs = [c**2 for c in self.realcoeffs]
        self.coeffs.extend([c**2 for c in self.imagcoeffs])
        # Now handle the cross-coefficients
        self.coeffs.extend([2*np.multiply.reduce(c) for c in combinations(self.realcoeffs, 2)])
        self.coeffs.extend([2*np.multiply.reduce(c) for c in combinations(self.imagcoeffs, 2)])

        # Do the same with the indices
        self.indices = [(i, i) for i in self.realindices]
        self.indices.extend([(i, i) for i in self.imagindices])
        self.indices.extend([i for i in combinations(self.realindices, 2)])
        self.indices.extend([i for i in combinations(self.imagindices, 2)])

        super(LinearOpticalSeries, self).__init__()
        
    def _getCoeffs(self):
        return self.coeffs
        
    def _getBasisFuncs(self):
        return [LinearOpticalet(self.lam_over_diam, o[0][0], o[0][1], o[1][0], o[1][1]) for o in
                self.indices]
        
    def _series_idx(self):
        return (self.__class__, self.lam_over_diam, len(self.aberrations))

        
class LinearOpticalet(galsim.GSObject):
    """A basis function in the Taylor series expansion of the optical wavefront.

    @param scale_radius   Set the size.
    @param n1             First radial index.
    @param m1             First azimuthal index.
    @param n2             Second radial index.
    @param m2             Second azimuthal index.
    """
    def __init__(self, scale_radius, n1, m1, n2, m2, gsparams=None):
        galsim.GSObject.__init__(
            self, galsim._galsim.SBLinearOpticalet(scale_radius,
                                                   n1, m1, n2, m2, gsparams=gsparams))

    def getScaleRadius(self):
        return self.SBProfile.getScaleRadius()

    def getIndices(self):
        return (self.SBProfile.getN1(), self.SBProfile.getM1(),
                self.SBProfile.getN2(), self.SBProfile.getM2())
        
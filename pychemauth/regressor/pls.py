"""
Projection to Latent Structures (PLS).

author: nam
"""
import copy

import matplotlib.pyplot as plt
import numpy as np
import scipy
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.cross_decomposition import PLSRegression
from sklearn.utils.validation import check_array, check_is_fitted, check_X_y

from pychemauth.preprocessing.scaling import CorrectedScaler
from pychemauth.utils import estimate_dof


class PLS(RegressorMixin, BaseEstimator):
    """
    Perform a Partial Least Squares Regression (PLS) aka Projection to Latent Structures Regression.

    Notes
    -----
    * X and y are always centered internally, y is never scaled.
    * A single, scalar output (y) is expected for each observation. This is to allow
    for outlier detection and analysis following [1-2].
    * Ref [2] illustrates how to extend this to multiple responses in the future (PLS2).

    [1] "Acceptance areas for multivariate classification derived by projection
    methods," Pomerantsev, Journal of Chemometrics 22 (2008) 601-609.
    [2] "Detection of Outliers in Projection-Based Modeling," Rodionova and Pomerantsev,
    Analytical Chemistry 92 (2020) 2656−2664.
    [3] "Concept and role of extreme objects in PCA/SIMCA," Pomerantsev, A. and
    Rodionova, O., Journal of Chemometrics 28 (2014) 429-438.
    """

    def __init__(
        self,
        n_components=1,
        alpha=0.05,
        gamma=0.01,
        scale_x=False,
        robust=True,
        sft=False,
    ):
        """
        Instantiate the class.

        Parameters
        ----------
        n_components : int
            Number of dimensions to project into. Should be in the range
            [1, min(n_samples-1, n_features)].
        alpha : float
            Type I error rate (signficance level).
        gamma : float
            Significance level for determining outliers.
        scale_x : bool
            Whether or not to scale X columns by the standard deviation.
        robust : bool
            Whether or not to apply robust methods to estimate degrees of freedom.
            True (default) is described in [3] and uses robust DoF estimation, otherwise
            classical estimators are used. If the dataset is clean (no outliers)
            it is best practice to use a classical method [3], however, to initially
            test for and potentially remove these points, a robust variant is recommended.
            This is why `True` is the default value.
        sft : bool
            Whether or not to use the iterative outlier removal scheme described
            in [2], called "sequential focused trimming."  If not used (default)
            robust estimates of parameters may be attempted; if the iterative
            approach is used, these robust estimates are only computed during the
            outlier removal loop(s) while the final "clean" data uses classical
            estimates.  This option may throw away data it is originally provided
            for training; it keeps only "regular" samples (inliers and extremes)
            to train the model.
        """
        self.set_params(
            **{
                "n_components": n_components,
                "alpha": alpha,
                "gamma": gamma,
                "scale_x": scale_x,
                "robust": robust,
                "sft": sft,
            }
        )
        self.is_fitted_ = False

    def set_params(self, **parameters):
        """Set parameters; for consistency with scikit-learn's estimator API."""
        for parameter, value in parameters.items():
            setattr(self, parameter, value)
        return self

    def get_params(self, deep=True):
        """Get parameters; for consistency with scikit-learn's estimator API."""
        return {
            "n_components": self.n_components,
            "alpha": self.alpha,
            "gamma": self.gamma,
            "scale_x": self.scale_x,
            "robust": self.robust,
            "sft": self.sft,
        }

    def column_y_(self, y):
        """Convert y to column format."""
        y = np.array(y)
        if y.ndim != 2:
            y = y[:, np.newaxis]

        return y

    def matrix_X_(self, X):
        """Check that observations are rows of X."""
        X = np.array(X)
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        assert (
            X.shape[1] == self.n_features_in_
        ), "Incorrect number of features given in X."

        return X

    def fit(self, X, y):
        """
        Fit the PLS model.

        Parameters
        ----------
        X : matrix-like
            Columns of features; observations are rows - will be converted to
            numpy array automatically. [n_samples, n_features]
        y : array-like
            Response values. Should only have a single scalar response for each
            observation. [n_samples, 1]

        Returns
        -------
        self
        """

        def train(X, y, robust):
            """
            Train the model.

            Parameters
            ----------
            X : ndarray
                X data to train on.
            y : ndarray
                y data to train on.
            robust : bool
                Whether or not to use robust parameter estimation in [3].
            """
            if scipy.sparse.issparse(X) or scipy.sparse.issparse(y):
                raise ValueError("Cannot use sparse data.")
            self.__X_ = np.array(X).copy()
            self.__X_, y = check_X_y(self.__X_, y, accept_sparse=False)
            # check_array(y, accept_sparse=False, dtype=None, force_all_finite=True)
            self.__y_ = self.column_y_(
                y
            )  # scikit-learn expects 1D array, convert to columns
            assert self.__y_.shape[1] == 1

            if self.__X_.shape[0] != self.__y_.shape[0]:
                raise ValueError(
                    "X ({}) and y ({}) shapes are not compatible".format(
                        self.__X_.shape, self.__y_.shape
                    )
                )
            self.n_features_in_ = self.__X_.shape[1]

            # 1. Preprocess X data
            self.__x_scaler_ = CorrectedScaler(
                with_mean=True, with_std=self.scale_x
            )  # Always center and maybe scale X
            self.__x_scaler_.fit(self.__X_)

            # 2. Preprocess Y data
            self.__y_scaler_ = CorrectedScaler(
                with_mean=True, with_std=False
            )  # Always center and maybe scale Y
            self.__y_scaler_.fit(self.__y_)

            # 3. Perform PLS
            upper_bound = np.min(
                [
                    self.__X_.shape[0] - 1,
                    self.__X_.shape[1],
                ]
            )
            lower_bound = 1
            if (
                self.n_components > upper_bound
                or self.n_components < lower_bound
            ):
                raise Exception(
                    "n_components must [{}, min(n_samples-1 [{}], \
    n_features [{}])] = [{}, {}].".format(
                        lower_bound,
                        self.__X_.shape[0] - 1,
                        self.__X_.shape[1],
                        lower_bound,
                        upper_bound,
                    )
                )

            self.__pls_ = PLSRegression(
                n_components=self.n_components,
                scale=self.scale_x,
                max_iter=10000,
            )

            # 4. Fit the projection
            self.__pls_.fit(
                self.__x_scaler_.transform(self.__X_),
                self.__y_scaler_.transform(self.__y_),
            )

            # 5. Characterize outliers according to [2]
            self.is_fitted_ = True

            h_vals, q_vals = self.h_q_(self.__X_)

            # As in the conclusions of [1], Nh ~ n_components is expected so good initial guess
            self.__Nh_, self.__h0_ = estimate_dof(
                h_vals, robust=robust, initial_guess=self.n_components
            )

            # As in the conclusions of [1], Nq ~ rank(X)-n_components is expected;
            # assuming near full rank then this is min(I,J)-n_components
            # (n_components<=J)
            self.__Nq_, self.__q0_ = estimate_dof(
                q_vals,
                robust=robust,
                initial_guess=np.min([len(q_vals), self.n_features_in_])
                - self.n_components,
            )

            self.__Nf_ = self.__Nh_ + self.__Nq_
            self.__f0_ = (
                self.__Nf_
            )  # This term is a matter of convention to match the literature

            z_vals = self.z_(
                self.__X_, self.__y_
            )  # Must come after fitting is otherwise complete
            self.__Nz_, self.__z0_ = estimate_dof(
                z_vals, robust=robust, initial_guess=self.__y_.shape[1]
            )

            self.__x_crit_ = scipy.stats.chi2.ppf(1.0 - self.alpha, self.__Nf_)
            self.__x_out_ = scipy.stats.chi2.ppf(
                (1.0 - self.gamma) ** (1.0 / self.__X_.shape[0]),
                self.__Nf_,
            )

            self.__xy_crit_ = scipy.stats.chi2.ppf(
                1.0 - self.alpha, self.__Nf_ + self.__Nz_
            )
            self.__xy_out_ = scipy.stats.chi2.ppf(
                (1.0 - self.gamma) ** (1.0 / self.__X_.shape[0]),
                self.__Nf_ + self.__Nz_,
            )

        # This is based on [2]
        if not self.sft:
            train(X, y, robust=self.robust)
            self.__sft_history_ = {}
        else:
            X_tmp = np.array(X).copy()
            y_tmp = np.array(y).ravel()
            total_data_points = X_tmp.shape[0]
            X_out = np.empty((0, X_tmp.shape[1]), dtype=type(X_tmp))
            y_out = np.array([], dtype=type(y_tmp))
            outer_iters = 0
            max_outer = 100
            max_inner = 100
            sft_tracker = {}
            while True:  # Outer loop
                if outer_iters >= max_outer:
                    raise Exception(
                        "Unable to iteratively clean data; exceeded maximum allowable outer loops (to eliminate swamping)."
                    )
                train(X_tmp, y_tmp, robust=True)
                _, outliers = self.check_xy_outliers(X_tmp, y_tmp)
                X_delete_ = X_tmp[outliers, :]
                y_delete_ = y_tmp[outliers]
                inner_iters = 0
                while np.sum(outliers) > 0:
                    if inner_iters >= max_inner:
                        raise Exception(
                            "Unable to iteratively clean data; exceeded maximum allowable inner loops (to eliminate masking)."
                        )
                    X_tmp = X_tmp[~outliers, :]
                    y_tmp = y_tmp[~outliers]
                    if len(X_tmp) == 0:
                        raise Exception(
                            "Unable to iteratively clean data; all observations are considered outliers."
                        )
                    train(X_tmp, y_tmp, robust=True)
                    _, outliers = self.check_xy_outliers(X_tmp, y_tmp)
                    X_delete_ = np.vstack((X_delete_, X_tmp[outliers, :]))
                    y_delete_ = np.concatenate((y_delete_, y_tmp[outliers]))
                    inner_iters += 1
                X_out = np.vstack((X_out, X_delete_))
                y_out = np.concatenate((y_out, y_delete_))
                assert (
                    X_tmp.shape[0] + X_out.shape[0] == total_data_points
                )  # Sanity check
                assert (
                    len(y_tmp) + len(y_out) == total_data_points
                )  # Sanity check

                # All inside X_tmp are inliers or extremes (regular objects) now.
                # Check that all outliers are predicted to be outliers in the latest version trained
                # on only inlier and extremes.
                outer_iters += 1
                sft_tracker[outer_iters] = {
                    "initially removed X": X_delete_,
                    "initially removed y": y_delete_,
                    "returned X": None,
                    "returned y": None,
                }
                if len(X_out) > 0:
                    _, outliers = self.check_xy_outliers(X_out, y_out)
                    X_return = X_out[~outliers, :]
                    y_return = y_out[~outliers]
                    X_out = X_out[outliers, :]
                    y_out = y_out[outliers]
                    if len(X_return) == 0:
                        break
                    else:
                        sft_tracker[outer_iters]["returned X"] = X_return
                        sft_tracker[outer_iters]["returned y"] = y_return
                        X_tmp = np.vstack((X_tmp, X_return))
                        y_tmp = np.concatenate((y_tmp, y_return))
                else:
                    break

            # Outliers have been iteratively found, and X_tmp is a consistent set of data to use
            # which is considered "clean" so should try to use classical estimates of the parameters.
            # train() assigns X_tmp to self.__X_ also. See [3].
            assert (
                X_out.shape[0] + self.__X_.shape[0] == total_data_points
            )  # Sanity check
            assert (
                len(y_out) + self.__y_.shape[0] == total_data_points
            )  # Sanity check
            train(X_tmp, y_tmp, robust=False)
            self.__sft_history_ = {
                "outer_loops": outer_iters,
                "removed": {"X": X_out, "y": y_out},
                "iterations": sft_tracker,
            }

        return self

    @property
    def sft_history(self):
        """Return the sequential focused trimming history."""
        return copy.deepcopy(self.__sft_history_)

    def h_q_(self, X):
        """Compute inner and outer (X) distances."""
        check_is_fitted(self, "is_fitted_")
        X = check_array(X, accept_sparse=False)
        X = self.matrix_X_(X)
        assert X.shape[1] == self.n_features_in_

        X_ = self.__x_scaler_.transform(X)
        x_scores = self.__pls_.transform(X_)

        x_scores_t_ = self.transform(self.__X_)
        h = np.diagonal(
            np.matmul(
                np.matmul(
                    x_scores,
                    np.linalg.inv(np.matmul(x_scores_t_.T, x_scores_t_)),
                ),
                x_scores.T,
            )
        )

        q = np.sum(
            (self.__pls_.inverse_transform(x_scores) - X_) ** 2,
            axis=1,
        )

        return h, q

    def f_(self, h, q):
        """Full (X) distance, Eq. 3 in [2]."""
        check_is_fitted(self, "is_fitted_")
        return (
            self.__Nh_ * np.array(h).ravel() / self.__h0_
            + self.__Nq_ * np.array(q).ravel() / self.__q0_
        )

    def z_(self, X, y):
        """Y residual squared, Eq. 7 in [2]."""
        return ((self.predict(X) - self.column_y_(y)) ** 2).ravel()

    def g_(self, X, y):
        """XY total distance, Eq. 9 in [2]."""
        h, q = self.h_q_(X)
        f = self.f_(h, q)
        z = self.z_(X, y)
        g = (
            self.__Nf_ * f / self.__f0_ + self.__Nz_ * z / self.__z0_
        )  # = f + Nz*z/z0
        return g

    def transform(self, X):
        """
        Project X into the PLS subspace to create the x-scores.

        Parameters
        ----------
        X : matrix-like
            Columns of features; observations are rows - will be converted to
            numpy array automatically.

        Returns
        -------
        x-scores : matrix-like
            Projection of X via PLS into a score space.
        """
        check_is_fitted(self, "is_fitted_")
        X = check_array(X, accept_sparse=False)
        X = self.matrix_X_(X)
        assert X.shape[1] == self.n_features_in_

        return self.__pls_.transform(self.__x_scaler_.transform(X))

    def fit_transform(self, X, y):
        """Fit and transform."""
        self.fit(X, y)
        return self.transform(X)

    def predict(self, X):
        """
        Predict the values for a given set of features.

        Parameters
        ----------
        X : matrix-like
            Columns of features; observations are rows - will be converted to
            numpy array automatically.

        Returns
        -------
        predictions : ndarray
            Predicted output for each observation.
        """
        check_is_fitted(self, "is_fitted_")
        X = check_array(X, accept_sparse=False)
        X = self.matrix_X_(X)
        assert X.shape[1] == self.n_features_in_

        return self.__y_scaler_.inverse_transform(
            self.__pls_.predict(self.__x_scaler_.transform(X))
        )

    def score(self, X, y):
        """
        Compute the coefficient of determination (R^2) as the score.

        Parameters
        ----------
        X : matrix-like
            Columns of features; observations are rows - will be converted to
            numpy array automatically.
        y : array-like
            Response values.
        """
        check_is_fitted(self, "is_fitted_")
        X = check_array(X, accept_sparse=False)
        X = self.matrix_X_(X)
        assert X.shape[1] == self.n_features_in_
        # check_array(y, accept_sparse=False, dtype=None, force_all_finite=True)
        y = self.column_y_(y)
        if X.shape[0] != y.shape[0]:
            raise ValueError(
                "X ({}) and y ({}) shapes are not compatible".format(
                    X.shape, y.shape
                )
            )

        ss_res = np.sum((self.predict(X) - y) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        return 1.0 - ss_res / ss_tot

    def check_x_outliers(self, X):
        """
        Check if outliers exist in the X data.

        This uses the X matrix's "full distance" in [2] (cf. Eq. 3).

        Parameters
        ----------
        X : matrix-like
            Columns of features; observations are rows - will be converted to
            numpy array automatically.

        Returns
        -------
        extremes, outliers : ndarray, ndarray
            Boolean mask of X if each point falls between acceptance threshold
            (belongs to class) and the outlier threshold (extreme), or beyond
            the outlier (outlier) threshold.
        """
        f = self.f_(*self.h_q_(X))

        extremes = (self.__x_crit_ <= f) & (f < self.__x_out_)
        outliers = f >= self.__x_out_

        return extremes, outliers

    def check_xy_outliers(self, X, y):
        """
        Check if outliers exist in the XY data.

        This uses the system's "total distance" in [2] (cf. Eq. 9).

        Parameters
        ----------
        X : matrix-like
            Columns of features; observations are rows - will be converted to
            numpy array automatically.
        y : array-like
            Response values.

        Returns
        -------
        extremes, outliers : ndarray, ndarray
            Boolean mask if each point falls between acceptance threshold
            (belongs to class) and the outlier threshold (extreme), or beyond
            the outlier (outlier) threshold.
        """
        g = self.g_(X, y)

        extremes = (self.__xy_crit_ <= g) & (g < self.__xy_out_)
        outliers = g >= self.__xy_out_

        return extremes, outliers

    def visualize(self, X, y, figsize=None):
        """
        Plot the chi-squared acceptance area with observations.

        Parameters
        ----------
        X : matrix-like
            Columns of features; observations are rows - will be converted to
            numpy array automatically.
        y : matrix-like
            Labels for observations in X.
        """
        check_is_fitted(self, "is_fitted_")
        X_ = self.matrix_X_(X)
        y_ = np.array(y)

        fig, axes = plt.subplots(nrows=1, ncols=2, figsize=figsize)

        # 1. X plot
        h_, q_ = self.h_q_(X)
        h_lim = np.linspace(0, self.__x_crit_ * self.__h0_ / self.__Nh_, 1000)
        h_lim_out = np.linspace(
            0, self.__x_out_ * self.__h0_ / self.__Nh_, 1000
        )
        q_lim = (
            (self.__x_crit_ - self.__Nh_ / self.__h0_ * h_lim)
            * self.__q0_
            / self.__Nq_
        )
        q_lim_out = (
            (self.__x_out_ - self.__Nh_ / self.__h0_ * h_lim_out)
            * self.__q0_
            / self.__Nq_
        )

        axes[0].plot(
            np.log(1.0 + h_lim / self.__h0_),
            np.log(1.0 + q_lim / self.__q0_),
            "g-",
        )
        axes[0].plot(
            np.log(1.0 + h_lim_out / self.__h0_),
            np.log(1.0 + q_lim_out / self.__q0_),
            "r-",
        )
        xlim, ylim = (
            1.1 * np.max(np.log(1.0 + h_lim_out / self.__h0_)),
            1.1 * np.max(np.log(1.0 + q_lim_out / self.__q0_)),
        )

        ext_mask, out_mask = self.check_x_outliers(X_)
        in_mask = (~ext_mask) & (~out_mask)
        for c, mask, label in [
            (
                "g",
                in_mask,
                "Regular =" + " ({})".format(np.sum(in_mask)),
            ),
            (
                "orange",
                ext_mask,
                "Extreme =" + " ({})".format(np.sum(ext_mask)),
            ),
            (
                "r",
                out_mask,
                "Outlier =" + " ({})".format(np.sum(out_mask)),
            ),
        ]:
            axes[0].plot(
                np.log(1.0 + h_[mask] / self.__h0_),
                np.log(1.0 + q_[mask] / self.__q0_),
                label=label,
                marker="o",
                lw=0,
                color=c,
                alpha=0.35,
            )
        xlim = np.max([xlim, 1.1 * np.max(np.log(1.0 + h_ / self.__h0_))])
        ylim = np.max([ylim, 1.1 * np.max(np.log(1.0 + q_ / self.__q0_))])
        axes[0].legend(loc="upper right")
        axes[0].set_xlim(0, xlim)
        axes[0].set_ylim(0, ylim)
        axes[0].set_xlabel(r"${\rm ln(1 + h/h_0)}$")
        axes[0].set_ylabel(r"${\rm ln(1 + q/q_0)}$")
        axes[0].set_title("Full Distance (X)")

        # 2. XY plot
        f_, z_ = self.f_(h_, q_), self.z_(X_, y_)
        f_lim = np.linspace(0, self.__xy_crit_ * self.__f0_ / self.__Nf_, 1000)
        f_lim_out = np.linspace(
            0, self.__xy_out_ * self.__f0_ / self.__Nf_, 1000
        )
        z_lim = (
            (self.__xy_crit_ - self.__Nf_ / self.__f0_ * f_lim)
            * self.__z0_
            / self.__Nz_
        )
        z_lim_out = (
            (self.__xy_out_ - self.__Nf_ / self.__f0_ * f_lim_out)
            * self.__z0_
            / self.__Nz_
        )

        axes[1].plot(
            np.log(1.0 + f_lim / self.__f0_),
            np.log(1.0 + z_lim / self.__z0_),
            "g-",
        )
        axes[1].plot(
            np.log(1.0 + f_lim_out / self.__f0_),
            np.log(1.0 + z_lim_out / self.__z0_),
            "r-",
        )
        xlim, ylim = (
            1.1 * np.max(np.log(1.0 + f_lim_out / self.__f0_)),
            1.1 * np.max(np.log(1.0 + z_lim_out / self.__z0_)),
        )

        ext_mask, out_mask = self.check_xy_outliers(X_, y_)
        in_mask = (~ext_mask) & (~out_mask)
        for c, mask, label in [
            (
                "g",
                in_mask,
                "Regular =" + " ({})".format(np.sum(in_mask)),
            ),
            (
                "orange",
                ext_mask,
                "Extreme =" + " ({})".format(np.sum(ext_mask)),
            ),
            (
                "r",
                out_mask,
                "Outlier =" + " ({})".format(np.sum(out_mask)),
            ),
        ]:
            axes[1].plot(
                np.log(1.0 + f_[mask] / self.__f0_),
                np.log(1.0 + z_[mask] / self.__z0_),
                label=label,
                marker="o",
                lw=0,
                color=c,
                alpha=0.35,
            )
        xlim = np.max([xlim, 1.1 * np.max(np.log(1.0 + f_ / self.__f0_))])
        ylim = np.max([ylim, 1.1 * np.max(np.log(1.0 + z_ / self.__z0_))])
        axes[1].legend(loc="upper right")
        axes[1].set_xlim(0, xlim)
        axes[1].set_ylim(0, ylim)
        axes[1].set_xlabel(r"${\rm ln(1 + f/f_0)}$")
        axes[1].set_ylabel(r"${\rm ln(1 + z/z_0)}$")
        axes[1].set_title("Total Distance (XY)")
        plt.tight_layout()

        return axes

    def _get_tags(self):
        """For compatibility with scikit-learn >=0.21."""
        return {
            "allow_nan": False,
            "binary_only": False,
            "multilabel": False,
            "multioutput": False,
            "multioutput_only": False,
            "no_validation": False,
            "non_deterministic": False,
            "pairwise": False,
            "poor_score": False,
            "requires_fit": True,
            "requires_positive_X": False,
            "requires_y": True,
            "requires_positive_y": False,
            "_skip_test": True,  # Skip since get_tags is unstable anyway
            "_xfail_checks": False,
            "stateless": False,
            "X_types": ["2darray"],
        }

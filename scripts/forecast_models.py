"""CPU estimators shared by training, chronological validation and saved artifacts."""
import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin

SEQUENCE_START = 13
SEQUENCE_LENGTH = 5


class LSTMRegressor(RegressorMixin, BaseEstimator):
    """Five ordered observed returns, with a separate current-context input branch."""
    def __init__(self, hidden_size=16, epochs=12, batch_size=256, learning_rate=0.003, random_state=42):
        self.hidden_size = hidden_size
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.random_state = random_state

    def _network(self, count):
        import torch
        # Sequential containers keep fitted artifacts pickleable across processes.
        return torch.nn.ModuleDict({
            'sequence': torch.nn.LSTM(1, self.hidden_size, batch_first=True),
            'head': torch.nn.Sequential(torch.nn.Linear(self.hidden_size + count, 16),
                                        torch.nn.Tanh(), torch.nn.Linear(16, 1))})

    def _forward(self, x):
        import torch
        sequence = x[:, SEQUENCE_START:SEQUENCE_START + SEQUENCE_LENGTH].unsqueeze(-1)
        context = torch.cat((x[:, :SEQUENCE_START], x[:, SEQUENCE_START + SEQUENCE_LENGTH:]), dim=1)
        output, _ = self.network_['sequence'](sequence)
        return self.network_['head'](torch.cat((output[:, -1, :], context), dim=1)).squeeze(-1)

    def fit(self, X, y):
        import torch
        from sklearn.preprocessing import RobustScaler
        torch.set_num_threads(2)
        torch.manual_seed(self.random_state)
        X = np.asarray(X, dtype=np.float32)
        self.n_features_in_ = X.shape[1]
        if self.n_features_in_ < SEQUENCE_START + SEQUENCE_LENGTH:
            raise ValueError('LSTM requires five ordered return features')
        self.scaler_ = RobustScaler().fit(X)
        # A shared scale preserves relative sizes between sequence timesteps.
        sequence = X[:, SEQUENCE_START:SEQUENCE_START + SEQUENCE_LENGTH]
        self.scaler_.center_[SEQUENCE_START:SEQUENCE_START + SEQUENCE_LENGTH] = np.median(sequence)
        q = np.quantile(sequence, [0.25, 0.75])
        self.scaler_.scale_[SEQUENCE_START:SEQUENCE_START + SEQUENCE_LENGTH] = max(float(q[1] - q[0]), 1e-6)
        self.target_mean_ = float(np.mean(y))
        self.target_scale_ = max(float(np.std(y)), 1e-6)
        inputs = torch.tensor(self.scaler_.transform(X), dtype=torch.float32)
        targets = torch.tensor((np.asarray(y) - self.target_mean_) / self.target_scale_, dtype=torch.float32)
        self.network_ = self._network(self.n_features_in_ - SEQUENCE_LENGTH)
        optimizer = torch.optim.AdamW(self.network_.parameters(), lr=self.learning_rate, weight_decay=0.01)
        self.network_.train()
        for _ in range(self.epochs):
            order = torch.randperm(len(inputs))
            for start in range(0, len(order), self.batch_size):
                indexes = order[start:start + self.batch_size]
                optimizer.zero_grad()
                loss = torch.nn.functional.smooth_l1_loss(self._forward(inputs[indexes]), targets[indexes])
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.network_.parameters(), 1.0)
                optimizer.step()
        self.network_.eval()
        return self

    def predict(self, X):
        import torch
        inputs = torch.tensor(self.scaler_.transform(np.asarray(X)), dtype=torch.float32)
        with torch.no_grad():
            values = [self._forward(batch).numpy() for batch in inputs.split(self.batch_size)]
        return np.concatenate(values) * self.target_scale_ + self.target_mean_


class MathematicalForecast(RegressorMixin, BaseEstimator):
    """Regularized learned equation for log return; coefficients use training data only."""
    def __init__(self, alpha=100):
        self.alpha = alpha

    def fit(self, X, y):
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import RobustScaler
        self.scaler_ = RobustScaler().fit(X)
        self.model_ = Ridge(alpha=self.alpha).fit(self.scaler_.transform(X), y)
        self.n_features_in_ = np.asarray(X).shape[1]
        return self

    def predict(self, X):
        return self.model_.predict(self.scaler_.transform(X))

    def equation(self, names):
        # Convert the scaled equation back into original feature units.
        coefficients = self.model_.coef_ / self.scaler_.scale_
        intercept = float(self.model_.intercept_ - coefficients @ self.scaler_.center_)
        return {'target': 'log(next_session_close / scan_price)', 'intercept': intercept,
                'coefficients': dict(zip(names, coefficients.tolist())),
                'percentConversion': '100 * (exp(predicted_log_return) - 1)'}

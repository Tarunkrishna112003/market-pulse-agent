"""CPU estimators shared by training, chronological validation and saved artifacts."""
import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin

SEQUENCE_START = 14
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
        return {'target': 'log(target_session_close / target_session_open)', 'intercept': intercept,
                'coefficients': dict(zip(names, coefficients.tolist())),
                'percentConversion': '100 * (exp(predicted_log_return) - 1)'}


class GatedAttentionRegressor(RegressorMixin, BaseEstimator):
    """Small gated context + lag-attention model; validation is supplied chronologically."""
    def __init__(self, hidden_size=32, epochs=60, batch_size=256, learning_rate=0.001,
                 dropout=0.15, weight_decay=0.01, patience=6, auxiliary_weight=0.1,
                 huber_delta=1.0, random_state=42, attention=True):
        self.hidden_size=hidden_size;self.epochs=epochs;self.batch_size=batch_size
        self.learning_rate=learning_rate;self.dropout=dropout;self.weight_decay=weight_decay
        self.patience=patience;self.auxiliary_weight=auxiliary_weight
        self.huber_delta=huber_delta;self.random_state=random_state;self.attention=attention

    def _network(self, count):
        import torch
        h=self.hidden_size
        return torch.nn.ModuleDict({
            'sequence':torch.nn.LSTM(1,h,batch_first=True),
            'attention':torch.nn.Linear(h,1),
            'gate':torch.nn.Linear(count,count),
            'context':torch.nn.Sequential(torch.nn.Linear(count,h),torch.nn.LayerNorm(h),torch.nn.GELU(),torch.nn.Dropout(self.dropout)),
            'shared':torch.nn.Sequential(torch.nn.Linear(h*2,h),torch.nn.LayerNorm(h),torch.nn.GELU(),torch.nn.Dropout(self.dropout)),
            'residual':torch.nn.Linear(h*2,h),
            'heads':torch.nn.Linear(h,4)})

    def _forward(self,x):
        import torch
        sequence=x[:,SEQUENCE_START:SEQUENCE_START+SEQUENCE_LENGTH].unsqueeze(-1)
        context=torch.cat((x[:,:SEQUENCE_START],x[:,SEQUENCE_START+SEQUENCE_LENGTH:]),dim=1)
        states,_=self.network_['sequence'](sequence)
        temporal=(states*torch.softmax(self.network_['attention'](states),dim=1)).sum(dim=1) if self.attention else states[:,-1,:]
        context=self.network_['context'](context*torch.sigmoid(self.network_['gate'](context)))
        joined=torch.cat((temporal,context),dim=1)
        return self.network_['heads'](self.network_['shared'](joined)+self.network_['residual'](joined))

    def fit(self,X,y,validation_data=None):
        import copy
        import torch
        from sklearn.preprocessing import RobustScaler
        torch.set_num_threads(2);torch.manual_seed(self.random_state)
        X=np.asarray(X,dtype=np.float32);y=np.asarray(y,dtype=np.float32)
        self.n_features_in_=X.shape[1]
        self.scaler_=RobustScaler().fit(X)
        lag=X[:,SEQUENCE_START:SEQUENCE_START+SEQUENCE_LENGTH]
        self.scaler_.center_[SEQUENCE_START:SEQUENCE_START+SEQUENCE_LENGTH]=np.median(lag)
        q=np.quantile(lag,[.25,.75]);self.scaler_.scale_[SEQUENCE_START:SEQUENCE_START+SEQUENCE_LENGTH]=max(float(q[1]-q[0]),1e-6)
        self.target_mean_=float(np.mean(y));self.target_scale_=max(float(np.std(y)),1e-6)
        inputs=torch.tensor(self.scaler_.transform(X),dtype=torch.float32)
        targets=torch.tensor((y-self.target_mean_)/self.target_scale_,dtype=torch.float32)
        directions=torch.tensor(y>0,dtype=torch.float32)
        self.network_=self._network(X.shape[1]-SEQUENCE_LENGTH)
        optimizer=torch.optim.AdamW(self.network_.parameters(),lr=self.learning_rate,weight_decay=self.weight_decay)
        best=float('inf');stale=0;checkpoint=None;self.epochs_trained_=0
        if validation_data is not None:
            vx,vy=validation_data
            vx=torch.tensor(self.scaler_.transform(vx),dtype=torch.float32)
            vy=torch.tensor((np.asarray(vy)-self.target_mean_)/self.target_scale_,dtype=torch.float32)
        for epoch in range(self.epochs):
            self.network_.train()
            for indexes in torch.randperm(len(inputs)).split(self.batch_size):
                optimizer.zero_grad();output=self._forward(inputs[indexes]);truth=targets[indexes]
                loss=torch.nn.functional.huber_loss(output[:,0],truth,delta=self.huber_delta)
                if self.auxiliary_weight:
                    direction=torch.nn.functional.binary_cross_entropy_with_logits(output[:,1],directions[indexes])
                    residual=truth[:,None]-output[:,2:4];quantiles=torch.tensor([.1,.9])
                    pinball=torch.maximum(quantiles*residual,(quantiles-1)*residual).mean()
                    loss=loss+self.auxiliary_weight*(direction+pinball)
                loss.backward();torch.nn.utils.clip_grad_norm_(self.network_.parameters(),1.0);optimizer.step()
            self.epochs_trained_=epoch+1
            if validation_data is not None:
                self.network_.eval()
                with torch.no_grad():score=float(torch.abs(self._forward(vx)[:,0]-vy).mean())
                if score<best-1e-5:best=score;checkpoint=copy.deepcopy(self.network_.state_dict());stale=0
                else:stale+=1
                if stale>=self.patience:break
        if checkpoint is not None:self.network_.load_state_dict(checkpoint)
        self.network_.eval();return self

    def predict_details(self,X):
        import torch
        inputs=torch.tensor(self.scaler_.transform(np.asarray(X)),dtype=torch.float32)
        with torch.no_grad():output=torch.cat([self._forward(batch) for batch in inputs.split(self.batch_size)]).numpy()
        return {'return':output[:,0]*self.target_scale_+self.target_mean_,
                'upProbability':1/(1+np.exp(-np.clip(output[:,1],-40,40))),
                'quantiles':np.sort(output[:,2:4],axis=1)*self.target_scale_+self.target_mean_}

    def predict(self,X):return self.predict_details(X)['return']


class WeightedForecast(RegressorMixin, BaseEstimator):
    """Already-fitted models blended in log-return space with nonnegative weights."""
    def __init__(self, models, weights):self.models=models;self.weights=weights
    def predict(self,X):return sum(weight*model.predict(X) for model,weight in zip(self.models,self.weights))


class ResidualMLPRegressor(GatedAttentionRegressor):
    """Residual tabular comparator using exactly the same input features."""
    def _network(self,count):
        import torch
        h=self.hidden_size;count+=SEQUENCE_LENGTH
        return torch.nn.ModuleDict({'gate':torch.nn.Linear(count,count),
            'input':torch.nn.Linear(count,h),
            'shared':torch.nn.Sequential(torch.nn.LayerNorm(h),torch.nn.GELU(),torch.nn.Dropout(self.dropout),torch.nn.Linear(h,h)),
            'heads':torch.nn.Linear(h,4)})
    def _forward(self,x):
        import torch
        state=self.network_['input'](x*torch.sigmoid(self.network_['gate'](x)))
        return self.network_['heads'](state+self.network_['shared'](state))

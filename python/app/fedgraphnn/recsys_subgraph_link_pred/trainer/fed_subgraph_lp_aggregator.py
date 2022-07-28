import logging

import numpy as np
import torch
import wandb
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
)

from fedml.core import ServerAggregator


class FedSubgraphLPAggregator(ServerAggregator):
    def get_model_params(self):
        return self.model.cpu().state_dict()

    def set_model_params(self, model_parameters):
        logging.info("set_model_params")
        self.model.load_state_dict(model_parameters)

    def test(self, test_data, device, args):
        pass

    def _test(self, test_data, device, val=True, metric=mean_absolute_error):
        model = self.model
        model.eval()
        model.to(device)
        metric = metric
        mae, rmse, mse = [], [], []

        for batch in test_data:
            batch.to(device)
            with torch.no_grad():
                train_z = model.encode(batch.x, batch.edge_train)
                if val:
                    link_logits = model.decode(train_z, batch.edge_val)
                else:
                    link_logits = model.decode(train_z, batch.edge_test)

                if val:
                    link_labels = batch.label_val
                else:
                    link_labels = batch.label_test
                score = metric(link_labels.cpu(), link_logits.cpu())
                mae.append(mean_absolute_error(link_labels.cpu(), link_logits.cpu()))
                rmse.append(mean_squared_error(link_labels.cpu(), link_logits.cpu(), squared=False))
                mse.append(mean_squared_error(link_labels.cpu(), link_logits.cpu()))
        return score, model, mae, rmse, mse

    def test_on_the_server(self, train_data_local_dict, test_data_local_dict, device, args=None) -> bool:
        logging.info("----------test_on_the_server--------")

        model_list, score_list, mae_list, rmse_list, mse_list = [], [], [], [], []
        for client_idx in test_data_local_dict.keys():
            test_data = test_data_local_dict[client_idx]
            score, model, mae, rmse, mse = self._test(test_data, device, val=False)

            for idx in range(len(model_list)):
                self._compare_models(model, model_list[idx])
            model_list.append(model)
            score_list.append(score)
            mae_list.append(mae)
            rmse_list.append(rmse)
            mse_list.append(mse)

            logging.info(
                "Client {}, Test {} = {}, mae = {}, rmse = {}, mse = {}".format(
                    client_idx, args.metric, score, mae, rmse, mse
                )
            )
            if args.enable_wandb:
                wandb.log(
                    {"Client {} Test/{}".format(client_idx, args.metric): score, "MAE, RMSE, MSE": [mae, rmse, mse],}
                )

        avg_score = np.mean(np.array(score_list))
        mae_score = np.mean(np.array(mae_list))
        rmse_score = np.mean(np.array(rmse_list))
        mse_score = np.mean(np.array(mse_list))

        logging.info(
            "Test {} = {}, mae = {}, rmse = {}, mse = {}".format(
                args.metric, avg_score, mae_score, rmse_score, mse_score
            )
        )
        if args.enable_wandb:
            wandb.log(
                {
                    "Client {} Test/{}".format(client_idx, args.metric): avg_score,
                    "MAE, RMSE, MSE = ": [mae_score, rmse_score, mse_score],
                }
            )

        return True

    def _compare_models(self, model_1, model_2):
        models_differ = 0
        for key_item_1, key_item_2 in zip(model_1.state_dict().items(), model_2.state_dict().items()):
            if torch.equal(key_item_1[1], key_item_2[1]):
                pass
            else:
                models_differ += 1
                if key_item_1[0] == key_item_2[0]:
                    logging.info("Mismatch found at", key_item_1[0])
                else:
                    raise Exception
        if models_differ == 0:
            logging.info("Models match perfectly! :)")

    def get_link_labels(self, pos_edge_index, neg_edge_index, device):
        num_links = pos_edge_index.size(1) + neg_edge_index.size(1)
        link_labels = torch.zeros(num_links, dtype=torch.float, device=device)
        link_labels[: pos_edge_index.size(1)] = 1.0
        return link_labels
